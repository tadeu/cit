from __future__ import with_statement

#===================================================================================================
# configure_submodules_path
#===================================================================================================
def configure_submodules_path():
    '''
    Configures sys.path to detect our submodule dependencies. Must be called before trying to do
    any other imports.
    '''
    import sys, os
    
    directory = os.path.abspath(os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(directory, 'jenkinsapi'))
    sys.path.insert(0, os.path.join(directory, 'pyyaml', 'lib'))
    
configure_submodules_path()

#===================================================================================================
# imports
#===================================================================================================
from jenkinsapi.exceptions import UnknownJob
from jenkinsapi.jenkins import Jenkins
import contextlib
import subprocess
import xml.etree.ElementTree as ET
import yaml
import os
import sys
import urllib2

#===================================================================================================
# cit commands
# ------------
#
# Functions below handle the actual "meat" of cit's commands.
#  
#===================================================================================================

#===================================================================================================
# create_feature_branch_job
#===================================================================================================
def create_feature_branch_job(jenkins, job_name, new_job_name, branch, user_email):
    try:
        job = jenkins.get_job(new_job_name)
    except UnknownJob:
        status = 'CREATED'
        job = jenkins.copy_job(job_name, new_job_name)
    else:
        status = 'UPDATED'
        
    print '%s => %s (%s)' % (job_name, new_job_name, status)
    
    original_job = jenkins.get_job(job_name)
    tree = ET.fromstring(original_job.get_config())
    
    branch_elements = list(tree.findall('.//hudson.plugins.git.BranchSpec/name'))
    if len(branch_elements) > 0:
        branch_elements[0].text = branch
    else:
        print '  warning: Could not find any branch spec to replace!'
    
    # If displayName exists adds the feature branch name to it.
    display_name_elem = tree.find('./displayName')
    if display_name_elem is not None:
        display_name_elem.text = '%s (%s)' % (display_name_elem.text, branch)
    
    recipient_elements = list(tree.findall('.//hudson.tasks.Mailer/recipients'))
    if len(recipient_elements) == 1:
        recipient_element = recipient_elements[0]
        recipient_element.text = user_email
        
    # remove properties from the build so we can use "start" to start-up jobs
    properties_elem = tree.find('./properties')
    if properties_elem is not None:
        for elem in properties_elem.findall('./hudson.model.ParametersDefinitionProperty'):
            properties_elem.remove(elem)
            
    # add a scm poll trigger for the build with 5 min intervals
    triggers_elem = tree.find('./triggers')
    scm_trigger = ET.SubElement(triggers_elem, 'hudson.triggers.SCMTrigger')
    ET.SubElement(scm_trigger, 'spec').text = 'H/5 * * * *'
    ET.SubElement(scm_trigger, 'ignorePostCommitHooks').text = 'false'
    
    # remove build triggers after this job
    publishers_elem = tree.find('./publishers')
    if publishers_elem is not None:
        for elem in publishers_elem.findall('./hudson.tasks.BuildTrigger'):
            publishers_elem.remove(elem)
             
    job.update_config(ET.tostring(tree))
    
    return job
        

        
#===================================================================================================
# cit_add
#===================================================================================================
def cit_add(branch, global_config):
    cit_file_name, job_config = load_cit_local_config(os.getcwd())
    
    if branch is None:
        branch = get_git_branch(cit_file_name)
    
    jenkins_url = global_config['jenkins']['url']
    jenkins = Jenkins(jenkins_url)
    for job_name, new_job_name in get_configured_jobs(branch, job_config):
        user_name, user_email = get_git_user(cit_file_name)
        create_feature_branch_job(jenkins, job_name, new_job_name, branch, user_email)
        
        
#===================================================================================================
# cit_rm
#===================================================================================================
def cit_rm(branch, global_config):
    cit_file_name, job_config = load_cit_local_config(os.getcwd())
    
    if branch is None:
        branch = get_git_branch(cit_file_name)
    
    jenkins_url = global_config['jenkins']['url']
    jenkins = Jenkins(jenkins_url)
    for _, new_job_name in get_configured_jobs(branch, job_config):
        if jenkins.has_job(new_job_name):
            jenkins.delete_job(new_job_name)
            print new_job_name, '(REMOVED)'
        else:
            print new_job_name, '(NOT FOUND)'
        
#===================================================================================================
# cit_start
#===================================================================================================
def cit_start(branch, global_config):        
    cit_file_name, job_config = load_cit_local_config(os.getcwd())
    
    if branch is None:
        branch = get_git_branch(cit_file_name)
    
    jenkins_url = global_config['jenkins']['url']
    jenkins = Jenkins(jenkins_url)
    
    for _, new_job_name in get_configured_jobs(branch, job_config):
        if jenkins.has_job(new_job_name):
            job = jenkins.get_job(new_job_name)
            if not job.is_running():
                job.invoke()
                status = '(STARTED)'
            else:
                status = '(RUNNING)'
        else:
            status = '(NOT FOUND)'
        print new_job_name, status
 
        
#===================================================================================================
# git helpers
# -----------
#
# Git-related helper functions to extract user name, current branch, etc. 
#  
#===================================================================================================


#===================================================================================================
# get_git_user
#===================================================================================================
def get_git_user(cit_file_name):
    with chdir(cit_file_name):
        user_name = check_output('git config --get user.name', shell=True).strip()
        user_email = check_output('git config --get user.email', shell=True).strip()
        return user_name, user_email
        
        
#===================================================================================================
# get_git_branch
#===================================================================================================
def get_git_branch(cit_file_name):        
    with chdir(cit_file_name):
        return check_output('git rev-parse --abbrev-ref HEAD', shell=True).strip()


#===================================================================================================
# cit configuration
# -----------------
#
# Functions and commands that deal with cit's configuration. 
#  
#===================================================================================================

#===================================================================================================
# cit_init
#===================================================================================================
def cit_init(global_config, stdin):
    cit_file_name, config = load_cit_local_config(os.getcwd())
    
    print 'Configuring jobs for feature branches: %s' % cit_file_name
    print 
    
    updated = 0
    while True:
        sys.stdout.write('Source job (empty to exit):      ')
        source_job = stdin.readline().strip()
        if not source_job:
            break
        
        sys.stdout.write('Feature job (shh, use $name):    ')
        fb_job = stdin.readline().strip()
        if not fb_job:
            break
        
        fb_data = {
            'source-job' : source_job,
            'feature-branch-job' : fb_job, 
        }
        config.setdefault('jobs', []).append(fb_data)
        updated += 1
        print 'Done! Next?'
        print
        
    print 
    if updated:
        f = file(cit_file_name, 'w')
        f.write(yaml.dump(config, default_flow_style=False))
        f.close()
        print 'Done! Configured %d job(s)!' % updated
    else:
        print 'Abort? Okaay.'
    
    
#===================================================================================================
# cit_install
#===================================================================================================
def cit_install(global_config_file, stdin):
    print '=' * 60
    print 'Configuration'
    print '=' * 60
    sys.stdout.write('- Enter Jenkins URL:   ')
    jenkins_url = stdin.readline().strip()
    if not jenkins_url.startswith('http'):
        jenkins_url = 'http://' + jenkins_url
        
    print
    print 'Checking Jenkins server...',
    try:
        Jenkins(jenkins_url)
    except urllib2.URLError, e:
        print 'ERROR (%s)' % e
    else:
        print 'OK'
    
    config = {
    'jenkins' : {
        'url' : jenkins_url,
        }
    }
    
    f = file(global_config_file, 'w')
    f.write(yaml.dump(config, default_flow_style=False))
    f.close()
    

#===================================================================================================
# get_configured_jobs
#===================================================================================================
def get_configured_jobs(branch, job_config):  
    for job_config in job_config['jobs']:
        job_name = job_config['source-job'] 
        new_job_name = job_config['feature-branch-job'].replace('$name', branch)
        yield job_name, new_job_name
        
        
#===================================================================================================
# load_cit_local_config
#===================================================================================================
def load_cit_local_config(from_dir):
    tries = 0
    max_tries = 20
    while True:
        gitdir = os.path.join(from_dir, '.git')
        if os.path.isdir(gitdir):
            break
        from_dir = os.path.dirname(from_dir)
        
        tries += 1    
        if tries >= max_tries:
            raise RuntimeError('could not find .git directory')
        
    cit_file_name = os.path.join(from_dir, '.cit.yaml')
    
    config = {}
    if os.path.isfile(cit_file_name):
        loaded_config = yaml.load(file(cit_file_name).read()) or {}
        config.update(loaded_config)
        
    return cit_file_name, config


#===================================================================================================
# main
#===================================================================================================
def main(argv, global_config_file=None, stdin=None):
    # default values
    if global_config_file is None:
        global_config_file = os.path.join(os.path.dirname(__file__), 'citconfig.yaml')
        
    if stdin is None:
        stdin = sys.stdin
        
    # --install option: used to initialize configuration
    if '--install' in argv:
        cit_install(global_config_file, stdin)
        return RETURN_CODE_OK
    
    # read global config
    if not os.path.isfile(global_config_file):
        print >> sys.stderr, 'could not find cit config file at: %s' % global_config_file
        return RETURN_CODE_CONFIG_NOT_FOUND
        
    global_config = yaml.load(file(global_config_file).read()) 
    
    # command dispatch
    if len(argv) <= 1:
        print_help() 
        return RETURN_CODE_OK
    elif argv[1] == 'init':
        cit_init(global_config, stdin)
        return RETURN_CODE_OK
    elif argv[1] in ('add', 'start', 'rm'):
        if len(argv) > 2:
            branch = argv[2]
        else:
            branch = None
        if argv[1] == 'add':
            cit_add(branch, global_config)
        elif argv[1] == 'start':
            cit_start(branch, global_config)
        elif argv[1] == 'rm':
            cit_rm(branch, global_config)
        return RETURN_CODE_OK
    else:
        print 'Unknown command: "%s"' % argv[1]
        print_help()
        return RETURN_CODE_UNKNOWN_COMMAND

    return RETURN_CODE_OK


# Error Codes --------------------------------------------------------------------------------------

RETURN_CODE_OK = 0 
RETURN_CODE_UNKNOWN_COMMAND = 2
RETURN_CODE_CONFIG_NOT_FOUND = 3 


#===================================================================================================
# print_help
#===================================================================================================
def print_help():
    print 'Commands:'    
    print     
    print '    init                   configures jobs for feature branches for this git repo'
    print '    add [BRANCH]           add a new feature branch job to Jenkins'
    print '    start [BRANCH]         starts a new build for the given feature branch'
    print '    rm [BRANCH]            removes job for feature branches given'
    print    


#===================================================================================================
# general utilities
# -----------------
# 
# General utilities that didn't fit in any other category. 
#
#===================================================================================================

#===================================================================================================
# chdir
#===================================================================================================
@contextlib.contextmanager        
def chdir(cwd):
    old_cwd = os.getcwd()
    if os.path.isfile(cwd):
        cwd = os.path.dirname(cwd)
    os.chdir(cwd)
    yield
    os.chdir(old_cwd)
    
    
#===================================================================================================
# check_output
#===================================================================================================
def check_output(*args, **kwargs):
    '''
    Support subprocess.check_output for Python < 2.7
    '''
    try:
        return subprocess.check_output(*args, **kwargs)
    except AttributeError:
        kwargs['stdout'] = subprocess.PIPE
        popen = subprocess.Popen(*args, **kwargs)
        stdout, stderr = popen.communicate()
        if popen.returncode != 0:
            raise subprocess.CalledProcessError
        return stdout

#===================================================================================================
# main
#===================================================================================================
if __name__ == '__main__':
    sys.exit(main(sys.argv)) 
