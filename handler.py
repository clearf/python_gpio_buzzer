# -*- coding: utf-8 -*-

import time
import os
import threading
from werkzeug.wrappers import Request, Response
from werkzeug.urls import url_quote 
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.utils import redirect
from werkzeug.wsgi import SharedDataMiddleware
from jinja2 import Environment, FileSystemLoader
from twilio import twiml
import syslog
from sqlalchemy import create_engine, Column, String, Boolean, Date, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import date
from subprocess import call

syslog.openlog(ident='buzzer', facility=syslog.LOG_LOCAL2)

def log(message):
    try:
     syslog.syslog(message.encode('utf-8'))
    except Exception as e:
     print "Can't log %s" % str(e)

class RelayIntf(object):
    def __init__(self, config):
      self.gpio_pin = config['gpio_pin']
      self.gpio_path = config['gpio_path']
      self.test_mode = config['test_mode']
      self.default_open_time = config['default_open_time']
      try:
        call([self.gpio_path, "mode",  str(self.gpio_pin), "out"])
      except Exception as e:
        log('GPIO problem in init') 
        log(str(e))
    def __del__(self): 
      call([self.gpio_path, "mode",  str(self.gpio_pin), "in"])
    def relay_high(self, open_time):
      if not self.test_mode:
        try:
          # open door
          call([self.gpio_path, "write", str(self.gpio_pin), "1"])
          log('Open ' + str(open_time))
          time.sleep(open_time)
          # close door
          call([self.gpio_path, "write", str(self.gpio_pin), "0"])
          log('Closed')
        except Exception as e:
          log('GPIO problem') 
          log(str(e))
      else: 
        log('Test mode, no opening')
    def open_door(self, open_time=None):
      if not open_time:
        open_time=self.default_open_time
      t = threading.Thread(target=self.relay_high, args=[open_time])
      t.setDaemon(True)
      t.start()
      return True

class Gatekeeper(object):
  def __init__(self, relay, config):
    print config
    self.relay = relay
    self.tts_path = config['tts_path']
    template_path = os.path.join(os.path.dirname(__file__), 'templates')
    self.jinja_env = Environment(loader=FileSystemLoader(template_path),
                                 autoescape=True)
    self.url_map = Map([
       Rule('/call', endpoint='call'),
      Rule('/manual', endpoint='manual'),
    ])
    
    try:
	self.AccountSid=os.environ['TWILIO_ACCOUNT_SID'] 
    except Exception as e: 
       log("Problem with Twilio?")
       log(str(e))
    self.db = create_engine('sqlite:///callers.sqlite')

  class Caller(declarative_base()):
    __tablename__ = 'Caller'
    phone_number=Column(String, primary_key=True)
    name=Column(String)
    is_test=Column(Boolean)
    valid_date=Column(Date)
    def __init__(self, phone_number, name, is_test, valid_date=None):
      self.phone_number = phone_number
      self.name = name
      self.is_test =  is_test
      self.valid_date=valid_date
    def __repr__(self):
      return "<Caller('%s', '%s', '%s', '%s')>" % (self.phone_number, self.name.encode("ascii", 'ignore'), 
          self.is_test, str(self.valid_date))


  def speak_message(self, message):
    def speak_message(message):
      log("%s" % url_quote(message))
      call([self.tts_path, url_quote(message)])
    try:
      t = threading.Thread(target=speak_message, args=[message])
      t.setDaemon(True)
      t.start()
    except Exception as e:
      log('Sound problem') 
      log(e)

  def check_authorized_caller(self, phoneNumber, test_call):
    try: 
      Session = sessionmaker(bind=self.db)
      session=Session()
      results=session.query(self.Caller).filter(self.Caller.phone_number==phoneNumber, self.Caller.is_test==test_call,
          or_(self.Caller.valid_date==None, self.Caller.valid_date<=date.today() )).all()
      print results
      return results[0]
    except Exception as e:
      log('DB Exception' + str(e))
      return False


  def render_template(self, template_name, **context):
    t = self.jinja_env.get_template(template_name)
    return Response(t.render(context), mimetype='text/html')

  def dispatch_request(self, request):
    adapter = self.url_map.bind_to_environ(request.environ)
    try:
        endpoint, values = adapter.match()
        return getattr(self, 'on_' + endpoint)(request, **values)
    except HTTPException, e:
        return e
  
  def application(self, environ, start_response):
    request = Request(environ)
    response = self.dispatch_request(request)
    return response(environ, start_response)

  def on_manual(self, request):
    phoneNumber=request.args.get('From')
    AccountSid=request.args.get('AccountSid')
    return self.render_template('manual.html', From=phoneNumber, AccountSid=AccountSid)


  def on_call(self, request):
    if request.method == 'GET':
      print "Boolean"
      return redirect('/manual')
    print request.form
    r=twiml.Response()
    phoneNumber=request.form['From']
    AccountSid=request.form['AccountSid']
    # Make sure the impostors at least know my acct key
    if AccountSid == self.AccountSid:
      log("Call from %s" % phoneNumber)
      result = self.check_authorized_caller(phoneNumber,False)
      if result: 
        log("Authorized Caller: %s" % result.name)
        if self.relay.open_door():
          log("opening")
          self.speak_message("Welcome home, %s" % result.name)
          r.reject("Busy") 
        else:
          log("Not authorized")
          r.say("Error with GPIO"); 
          self.speak_message("Error when buzzing in " % results.name)
    else:
      log("Improper SID sent: %s" % AccountSid)
      r.reject("Busy") 
    response = Response(str(r), mimetype='text/xml')
    return response

  def __call__(self, environ, start_response):
    return self.application(environ, start_response)

def make_app(config_file="./config"):
  import json
  def generate_config(config_file):
    config={}
    try:
       with open(config_file, 'r') as f: 
          config=json.load(f)
          f.close()
    except IOError as e:
        print 'Using default config'
        config={'gpio_pin': 11, 'gpio_path': '/usr/local/bin/gpio', 'tts_path': '/var/www/buzzer/pythonws/text_to_speech.sh', 
            'test_mode': False, 'default_open_time': 10} 
        try: 
          # If the config file doesn't exist, write it
            print "Writing config to file"
            with open(config_file, 'w') as f:
              json.dump(config, f)
              f.close()
        except IOError as e:
          print "Unable to write config: ", e
    return config
  config = generate_config(config_file)
  log("Loading...")
  relay = RelayIntf(config)
  log("Relay Loaded...")
  web_app = Gatekeeper(relay, config)
  web_app = SharedDataMiddleware(web_app, {
            '/static':  os.path.join(os.path.dirname(__file__), 'static')
  })
  log("Gatekeeper Loaded...")
  return web_app

if __name__ == '__main__':
  web_app = make_app()
  from werkzeug.serving import run_simple
  print "Starting server..."
  run_simple('', 5000, web_app, use_reloader=True)
