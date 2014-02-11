import time
import os
import subprocess
import threading
from werkzeug.wrappers import Request, Response
from twilio import twiml
import syslog
from sqlalchemy import create_engine, Column, String, Boolean, Date, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import date
from subprocess import call

syslog.openlog(ident='buzzer', facility=syslog.LOG_LOCAL2)

def log(message):
  syslog.syslog(str(message))

class RelayIntf(object):
    def __init__(self, config):
      self.gpio_pin = config['gpio_pin']
      self.gpio_path = config['gpio_path']
      try:
        call([self.gpio_path, "mode",  str(self.gpio_pin), "out"])
      except Exception as e:
        log('GPIO problem') 
        log(e)
    def __del__(self): 
      call([self.gpio_path, "mode",  str(self.gpio_pin), "in"])
    def relay_high(self, open_time):
      try:
        # open door
        call([self.gpio_path, "write", str(self.gpio_pin), "1"])
        time.sleep(open_time)
        # close door
        call([self.gpio_path, "write", str(self.gpio_pin), "0"])
      except Exception as e:
        log('GPIO problem') 
        log(e)
    def open_door(self, open_time=10):
      t = threading.Thread(target=self.relay_high, args=[open_time])
      t.setDaemon(True)
      t.start()
      return True

class Gatekeeper(object):
  def __init__(self, relay, config):
    print config
    self.relay = relay
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
      return "<Caller('%s', '%s', '%s', '%s')>" % (self.phone_number, self.name, self.is_test, str(self.valid_date))

  def check_authorized_caller(self, phoneNumber, test_call):
    try: 
      Session = sessionmaker(bind=self.db)
      session=Session()
      results=session.query(self.Caller).filter(self.Caller.phone_number==phoneNumber, self.Caller.is_test==test_call,
          or_(self.Caller.valid_date==None, self.Caller.valid_date<=date.today() )).all()
      print results
      return results != []
    except Exception as e:
      log('DB Exception' + str(e))
      return False

  def application(self, environ, start_response):
    request = Request(environ)
    r=twiml.Response()
    phoneNumber=request.args.get('From')
    AccountSid=request.args.get('AccountSid')
    # Make sure the impostors at least know my acct key
    if AccountSid == self.AccountSid:
      log("Call from %s" % phoneNumber)
      if self.check_authorized_caller(phoneNumber,False):
        log("Authorized Caller!")
        if True:
          try:
            subprocess.check_output(["/usr/bin/mpg321", 
              "http://s3-us-west-2.amazonaws.com/hobby.lyceum.dyn.dhs.org/buzzer/r2d2-squeaks2.mp3"])
          except subprocess.CalledProcessError as e:
            log('Exception' + str(e))
            r.reject("Busy")
        elif self.relay.open_door():
          log("opening")
          r.reject("Busy") 
        else:
          log("Not authorized")
          r.say("Error with GPIO"); 
    else:
      log("Improper SID sent")
      r.reject("Busy") 
    response = Response(str(r), mimetype='text/xml')
    return response(environ, start_response)

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
        config={'gpio_pin': 11, 'gpio_path': '/usr/local/bin/gpio'} 
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
  log("Gatekeeper Loaded...")
  return web_app

if __name__ == '__main__':
  web_app = make_app()
  from werkzeug.serving import run_simple
  print "Starting server..."
  run_simple('', 5000, web_app, use_reloader=True)
