import subprocess
import sys
import re
import yaml
import os
import datetime
import argparse
from pymongo import MongoClient

argparser = argparse.ArgumentParser(description = '')
argparser.add_argument('--config', metavar = 'file', dest = 'yamlConfig', required = True, help = '')
argparser.add_argument('--job-owner', metavar = 'name', dest = 'jobOwner', required = True, help = '')
argparser.add_argument('--job-number', metavar = 'number', dest = 'jobNumber', type = int, required = True, help = '')
argparser.add_argument('--set-status', metavar = 'status', dest = 'jobStatus', required = True, help = '')

def submitSlurmJob(db, jobOwner, jobNumber):
   document = db.jobs.find_one({'owner': jobOwner, 'number': jobNumber})
 
   if not document:
      raise Exception()

   jobLogStd = os.path.join(document['log'], 'slurm.std')
   jobLogErr = os.path.join(document['log'], 'slurm.err')

   p = subprocess.Popen(['sbatch', '-o', jobLogStd, '-e', jobLogErr, 'job_capsule.sh', jobOwner, str(jobNumber)], stderr = subprocess.PIPE, stdout = subprocess.PIPE)
   stdout, stderr = p.communicate()
   returncode = p.returncode

   jobSlurmId = None

   if len(stderr) == 0 and returncode == 0:
      okMessagePattern = re.compile('^Submitted batch job ([1-9][0-9]*)$')
      match = okMessagePattern.match(stdout)
      if match:
         jobSlurmId = match.group(1)         

   result = db.jobs.update_one({
      'owner': jobOwner, 
      'number': jobNumber}, {
      '$set': {
         'queued_on_date': datetime.datetime.utcnow(),
         'queued_stdout': stdout,
         'queued_stderr': stderr,
         'queued_returncode': returncode,
         'slurm_job_id': jobSlurmId
      }
   })

#   p = subrocess.Popen(['sbatch', '-o', jobLogStd, '-e', jobLogErr, '-d', 'afterok:...', 'afterok.sh', jobOwner, str(jobNumber)], stderr = subprocess.PIPE, stdout = subprocess.PIPE)
#   p = subrocess.Popen(['sbatch', '-o', jobLogStd, '-e', jobLogErr, '-d', 'afternotok:...', 'afternotok.sh', jobOwner, str(jobNumber)], stderr = subprocess.PIPE, stdout = subprocess.PIPE)
   

   if result.modified_count != 1:
      raise Exception()

def updateJob(yamlConfig, jobOwner, jobNumber, jobStatus):
   config = yaml.load(file(yamlConfig, 'r'))
   mongo_host = config['mongo_host']
   mongo_port = config['mongo_port']
   mongo_db = config['mongo_db']

   client = MongoClient(mongo_host, mongo_port)
   db = client[mongo_db]

   document = db.jobs.find_one({'owner': jobOwner, 'number': jobNumber})
   if not document:
      return 1

   if jobStatus == 'started':
      result = db.jobs.update_one({
         'owner': jobOwner,
         'number': jobNumber}, {
         '$set': {
            'started_on_date': datetime.datetime.utcnow()
         }
      })
      print 'here '
      if result.modified_count != 1:
         return 1
   elif jobStatus == 'finished':
      result = db.jobs.update_one({
         'owner': jobOwner,
         'number': jobNumber}, {
         '$set': {
            'finished_on_date': datetime.datetime.utcnow()
         }
      })
      if result.modified_count != 1:
         return 1
   else:
      return 1

   return 0
   
if __name__ == '__main__':
   args = argparser.parse_args()
   updateJob(args.yamlConfig, args.jobOwner, args.jobNumber, args.jobStatus)
