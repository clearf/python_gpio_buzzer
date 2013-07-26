import time
import os
import threading
from werkzeug.wrappers import Request, Response
from twilio import twiml
import syslog
from sqlalchemy import create_engine, Column, String, Boolean, Date, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import date

import RPi.GPIO as GPIO

syslog.openlog(ident='buzzer', facility=syslog.LOG_LOCAL2)

def log(message):
  syslog.syslog(str(message))

class RelayIntf(object):
    def __init__(self, config):
      self.gpio_pin = config['gpio_pin']
      GPIO.setmode(GPIO.BCM) # to use RPi board pinouts
      GPIO.setup(self.gpio_pin, GPIO.OUT)
      GPIO.output(self.gpio_pin, GPIO.LOW)
    def __del__(self):
      GPIO.cleanup()
    def relay_high(self, open_time):
      try:
        # open door
        GPIO.output(self.gpio_pin, GPIO.HIGH)
        time.sleep(self.open_time)
        # close door
        GPIO.output(self.gpio_pin, GPIO.LOW)
      except RuntimeError as e:
        log('GPIO not available. Privilege issue?')
        log(e)
    def open_door(self, open_time=10):
      self.open_time = open_time
      t = threading.Thread(target=self.relay_high(open_time))
      t.setDaemon(True)
      t.start()

class Gatekeeper(object):
  def __init__(self, relay, config):
    print config
    self.relay = relay
    self.AccountSid=os.environ['TWILIO_ACCOUNT_SID'] 
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
        #log("Authorized Caller!")
        if self.relay.open_door():
          print "opening"
          r.reject("Busy") 
        else:
          r.say("Error with GPIO"); 
    else:
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
        config={'gpio_pin': 7} 
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
  relay = RelayIntf(config)
  web_app = Gatekeeper(relay, config)
  return web_app

if __name__ == '__main__':
  web_app = make_app()
  from werkzeug.serving import run_simple
  print "Starting server..."
  run_simple('', 5000, web_app, use_reloader=True)
