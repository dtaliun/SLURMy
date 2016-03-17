from flask import Flask, g, render_template, request, session, redirect, url_for, abort, jsonify, send_file 
from pymongo import MongoClient, DESCENDING
from bson import objectid
import datetime
from math import ceil
import yaml
import os
import slurmytron

app = Flask(__name__)
app.secret_key = 'very secret'

config = yaml.load(file('config.yaml', 'r'))
app_name = config['app_name']
mongo_host = config['mongo_host']
mongo_port = config['mongo_port']
mongo_db = config['mongo_db']
users_workspace = config['users_workspace']

def connect_db():
   client = MongoClient(mongo_host, mongo_port)
   return client[mongo_db]

def get_db():
   if not hasattr(g, 'mongodb'):
      print 'open db'
      g.mongodb = connect_db()
   return g.mongodb

@app.teardown_appcontext
def close_db(exception):
   if hasattr(g, 'mongodb'):
      print 'ala close db'
#      g.mongodb.close()

@app.route('/', methods = ['GET', 'POST'])
def login():
   error = None
   if request.method == 'POST':
      email = request.form['email']
      password = request.form['password']
      if not email:
         error = 'Sorry, you forgot to enter your email address'
      elif not password:
         error = 'Sorry, you forgot to enter your password'
      else:
         db = get_db()
         document = db.users.find_one({'email': email})
         if not document:
            error = 'Invalid email address or password'
         elif document['password'] != password:
            error = 'Invalid email address or password'
         else:
            session['user'] = email
            return redirect(url_for('home'))
   return render_template('login.html', app_name = app_name, error = error)

@app.route('/register', methods = ['GET', 'POST'])
def register():
   error = None
   success = None
   if request.method == 'POST':
      db = get_db()
      name = request.form['name']
      email = request.form['email']
      password = request.form['password'] 
      if not name:
         error = 'Sorry, you forgot to enter your name'
      elif not email:
         error = 'Sorry, you forgot to enter your email address'
      elif not password:
         error = 'Sorry, you forgot to enter your password'
      elif db.users.find_one({'email': email}):
         error = 'Provided user name or email address cannot be registered'
      elif db.users.find_one({'name': name}):
         error = 'Provided user name or email address cannot be registered'
      else:
         home_path = os.path.join(users_workspace, email.replace('@', '.')) 
         db.users.insert({
            'name': name, 
            'email': email, 
            'password': password, 
            'home': home_path,
            'registered_on': datetime.datetime.utcnow(), 
            'confirmed_on': None,
            'modified_on': None,
            'accessed_on': None})
         os.mkdir(home_path)
         success = True  
         #return redirect(url_for('login'))
   return render_template('register.html', app_name = app_name, error = error, success = success)

@app.route('/logout')
def logout():
   session.pop('user', None)
   return redirect(url_for('login'))

@app.route('/home')
def home():
   user = session.get('user')
   if not user:
      abort(401)

   db = get_db()
   jobs = dict()

   jobs['submitted'] = db.jobs.find({'owner': user, 'submitted_on_date': {'$ne': None}, 'queued_on_date': None}).count()
   jobs['queued'] = db.jobs.find({'owner': user, 'queued_on_date': {'$ne': None}, 'started_on_date': None}).count()
   jobs['running'] = db.jobs.find({'owner': user, 'started_on_date': {'$ne': None}, 'finished_on_date': None}).count()
   jobs['finished'] = db.jobs.find({'owner': user, 'finished_on_date': {'$ne': None}}).count()

   document = db.users.find_one({'email': user})
   profile = {'name': document['name'], 'email': document['email']}

   return render_template('home.html', app_name = app_name, jobs = jobs, profile = profile)

@app.route('/addjob')
def addjob():
   user = session.get('user')
   if not user:
      abort(401)
   return render_template('addjob.html', app_name = app_name, error = None)

@app.route('/uploadjob', methods = ['POST'])
def uploadjob():
   user = session.get('user')
   if not user:
      abort(401)
   
   name = request.form['name']
   if not name:
      return 'Job name is missing', 400
   
   description = request.form['description']
   if not description:
      return 'Job description is missing', 400   

   files = request.files.getlist('files')
   if not files or sum([len(f.filename) for f in files]) <= 0:
      return 'No files to upload', 400
      
   db = get_db()

   document = db.jobs.find_one({'owner': user}, sort = [('number', DESCENDING)])
   if document:
      number = int(document['number']) + 1 
   else:
      number = 1

   document = db.users.find_one({'email': user})
    
   workspace_path = os.path.join(document['home'], str(number))
   input_path = os.path.join(workspace_path, 'input')
   log_path = os.path.join(workspace_path, 'log')
   output_path = os.path.join(workspace_path, 'output')

   _id = db.jobs.insert_one({
      'number': number,
      'name': name, 
      'description': description, 
      'owner': user,
      'workspace': workspace_path,
      'input': input_path,
      'log': log_path,
      'output': output_path, 
      'submitted_on_date': datetime.datetime.utcnow(),
      'queued_on_date': None, 
      'queued_stdout': None,
      'queued_stderr': None,
      'queued_returncode': None,
      'slurm_job_id': None,
      'started_on_date': None, 
      'finished_on_date': None}).inserted_id
    
   os.mkdir(workspace_path)
   os.mkdir(input_path)
   os.mkdir(log_path)
   os.mkdir(output_path)

   for f in files:
      if f.filename:
         f.save(os.path.join(input_path, f.filename))      

   result = db.jobs.update_one({'_id': _id }, {'$set': {'uploaded_on_date': datetime.datetime.utcnow()}})

   slurmytron.submitSlurmJob(db, user, number)

   return 'Job uploaded', 200 

@app.route('/jobs', methods = ['GET'])
def jobs():
   user = session.get('user')
   if not user:
      abort(401)

   page = request.args.get('page', None)
   size = request.args.get('size', None)
   
   db = get_db()

   jobs_count = db.jobs.find({'owner': user}).count()

   if not page or int(page) < 1:
      page = 1

   if not size or int(size) < 1:
      size = jobs_count

   pages_count = int(ceil(jobs_count / float(size)))

   jobs = list(db.jobs.find({'owner': user}, sort = [('_id', DESCENDING)]).skip((int(page) - 1) * int(size)).limit(int(size)))

   for job in jobs:
      if job['finished_on_date']:
         job['status'] = 'Finished'
      elif job['started_on_date']:
         job['status'] = 'Running'
      elif job['queued_on_date']:
         job['status'] = 'Waiting'
      else:
         job['status'] = 'Unknown' # we should not show such things?
   
   return render_template('jobs.html', app_name = app_name, pages_count = pages_count, page = int(page), jobs = jobs)

@app.route('/job', methods = ['GET'])
def job():
   user = session.get('user')
   if not user:
      abort(401)

   number = request.args.get('number', None)
   db = get_db() 
 
   document = db.jobs.find_one({'owner': user, 'number': int(number)})

   output_path = document['output']

   file_names = next(os.walk(output_path))[2]
   file_sizes = [os.path.getsize(os.path.join(output_path, f)) / 1000 for f in file_names] 
   
   files = zip(file_names, file_sizes)

   job = {
      'number': document['number'],
      'name': document['name'],
      'submitted_on_date': document['submitted_on_date'].strftime('%Y-%m-%d %H:%M'),
      'finished_on_date': None
   }

   return render_template('job.html', app_name = app_name, job = job, result_files = files)

@app.route('/result', methods = ['GET'])
def result():
   user = session.get('user')
   if not user:
      abort(401)

   number = request.args.get('number', None)
   file_name = request.args.get('name', None)

   db = get_db()

   document = db.jobs.find_one({'owner': user, 'number': int(number)}) 
   output_path = document['output']

   file_path = os.path.join(output_path, file_name)

   return send_file(file_path, attachment_filename = file_name, as_attachment = True)

@app.route('/profile', methods = ['GET'])
def profile():
   user = session.get('user')
   if not user:
      abort(401)

   db = get_db()

   document = db.users.find_one({'email': user})

   profile = {
      'name': document['name'],
      'email': document['email'],
      'registered': document['registered_on_date'].strftime('%Y-%m-%d %H:%M'),
      #'modified': document['registered_on_date'].strftime('%Y-%m-%d %H:%M')
      'modified': None
   }

   return render_template('profile.html', app_name = app_name, profile = profile)

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=5000)
