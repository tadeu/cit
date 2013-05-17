from __future__ import with_statement
from jenkinsapi.jenkins import Jenkins
from jenkinsapi.exceptions import UnknownJob
import xml.etree.ElementTree as ET
import os
import sys
import yaml
import subprocess
import contextlib
 
 
#===================================================================================================
# create_feature_branch_job
#===================================================================================================
def create_feature_branch_job(jenkins, job_name, new_job_name, branch, user_email):
    try:
        job = jenkins.get_job(new_job_name)
    except UnknownJob:
        print 'Copying job "%s" to "%s"...' % (job_name, new_job_name)
        job = jenkins.copy_job(job_name, new_job_name)
        
    print 'Updating configuration for job "%s"' % new_job_name
    tree = ET.fromstring(job.get_config())
    
    branch_elements = list(tree.findall('.//hudson.plugins.git.BranchSpec/name'))
    if len(branch_elements) > 0:
        old_branch = branch_elements[0].text
        branch_elements[0].text = branch
        print '  Branch changed to "%s" (was "%s")' % (branch, old_branch)
    else:
        print '  Could not find any branch spec to replace!'
    
    recipient_elements = list(tree.findall('.//hudson.tasks.Mailer/recipients'))
    if len(recipient_elements) == 1:
        recipient_element = recipient_elements[0]
        recipient_element.text = user_email
        print '  Set "%s" as email recipient for build results.' % user_email
            
    job.update_config(ET.tostring(tree))
    
    return job
        

     
#===================================================================================================
# _get_configured_jobs
#===================================================================================================
def _get_configured_jobs(branch, job_config):  
    for job_config in job_config['jobs']:
        job_name = job_config['source-job'] 
        new_job_name = job_config['feature-branch-job'].replace('$fb', branch)
        yield job_name, new_job_name   
        
        
#===================================================================================================
# cit_add
#===================================================================================================
def cit_add(branch, global_config):
    cit_file_name, job_config = load_cit_config(os.getcwd())
    
    jenkins_url = global_config['jenkins']['url']
    jenkins = Jenkins(jenkins_url)
    for job_name, new_job_name in _get_configured_jobs(branch, job_config):
        user_name, user_email = get_git_user(cit_file_name)
        create_feature_branch_job(jenkins, job_name, new_job_name, branch, user_email)
        
        
#===================================================================================================
# cit_rm
#===================================================================================================
def cit_rm(branch, global_config):
    cit_file_name, job_config = load_cit_config(os.getcwd())
    
    if branch is None:
        branch = get_git_branch(cit_file_name)
    
    jenkins_url = global_config['jenkins']['url']
    jenkins = Jenkins(jenkins_url)
    for _, new_job_name in _get_configured_jobs(branch, job_config):
        if jenkins.has_job(new_job_name):
            jenkins.delete_job(new_job_name)
            print new_job_name, '(REMOVED)'
        else:
            print new_job_name, '(NOT FOUND)'
        
#===================================================================================================
# cit_start
#===================================================================================================
def cit_start(branch, global_config):        
    cit_file_name, job_config = load_cit_config(os.getcwd())
    
    if branch is None:
        branch = get_git_branch(cit_file_name)
    
    jenkins_url = global_config['jenkins']['url']
    jenkins = Jenkins(jenkins_url)
    
    for _, new_job_name in _get_configured_jobs(branch, job_config):
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
# get_git_user
#===================================================================================================
def get_git_user(cit_file_name):
    with chdir(cit_file_name):
        user_name = subprocess.check_output('git config --get user.name', shell=True).strip()
        user_email = subprocess.check_output('git config --get user.email', shell=True).strip()
        return user_name, user_email
        
        
#===================================================================================================
# get_git_branch
#===================================================================================================
def get_git_branch(cit_file_name):        
    with chdir(cit_file_name):
        return subprocess.check_output('git rev-parse --abbrev-ref HEAD', shell=True).strip()


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
# main
#===================================================================================================
def main(argv, global_config_file=None, stdin=None):
    # default values
    if global_config_file is None:
        global_config_file = os.path.join(os.path.dirname(__file__), 'citconfig.yaml')
        
    if stdin is None:
        stdin = sys.stdin
        
    # read global config
    if not os.path.isfile(global_config_file):
        sys.exit('could not find cit config file at: %s' % global_config_file)
        
    global_config = yaml.load(file(global_config_file).read()) 
    
    # command dispatch
    if len(argv) <= 1:
        print_help() 
        return 1
    elif argv[1] == 'config':
        cit_config(global_config, stdin)
        return 0
    elif argv[1] == 'add':
        cit_add(argv[2], global_config)
        return 0
    elif argv[1] in ('start', 'rm'):
        if len(argv) > 2:
            branch = argv[2]
        else:
            branch = None
        if argv[1] == 'start':
            cit_start(branch, global_config)
        elif argv[1] == 'rm':
            cit_rm(branch, global_config)
        return 0
    else:
        print 'Unknown command:', argv[1]
        print_help()
        return 2

    return 0

#===================================================================================================
# print_help
#===================================================================================================
def print_help():
    print 'Commands:'    
    print     
    print '    config:            configures jobs for feature branches'
    print '    add BRANCH:        add a new feature branch job to Jenkins'
    print '    start [BRANCH]:    starts a new build for the given feature branch'
    print    


#===================================================================================================
# cit_config
#===================================================================================================
def cit_config(global_config, stdin):
    cit_file_name, config = load_cit_config(os.getcwd())
    
    print 'Configuring jobs for feature branches: %s' % cit_file_name
    print 
    
    updated = False
    while True:
        sys.stdout.write('Source job (empty to exit): ')
        source_job = stdin.readline().strip()
        if not source_job:
            break
        
        sys.stdout.write('Feature branch job, use $fb to replace by branch name: ')
        fb_job = stdin.readline().strip()
        if not fb_job:
            break
        
        fb_data = {
            'source-job' : source_job,
            'feature-branch-job' : fb_job, 
        }
        config.setdefault('jobs', []).append(fb_data)
        updated = True
        
    print 
    if updated:
        f = file(cit_file_name, 'w')
        f.write(yaml.dump(config, default_flow_style=False))
        f.close()
        print 'Configuration updated.'
    else:
        print 'Aborted.'
    
        
#===================================================================================================
# load_cit_config
#===================================================================================================
def load_cit_config(from_dir):
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
if __name__ == '__main__':
    sys.exit(main(sys.argv)) 
