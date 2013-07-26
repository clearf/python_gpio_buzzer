import serial
import time
import threading
from werkzeug.wrappers import Request, Response
from twilio import twiml
import syslog
from sqlalchemy import create_engine, Column, String, Boolean, Date, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import date

syslog.openlog(ident='buzzer', facility=syslog.LOG_LOCAL2)


def log(message):
    syslog.syslog(str(message))

class Serialer(object):
    def __init__(self, config):
        self.config = config
        self.init_serial()

    def __del__(self):
        self.serial.close()

    def init_serial(self):
        if hasattr(self, 'ser'):
            log("Closing serial") 
            self.ser.close()
            del self.ser
        try:
            log('Init Serial')
            log(self.config['serial_baud'])
            self.ser = serial.Serial(self.config['serial_port'],
                                     self.config['serial_baud'],
                                     timeout=1, writeTimeout=1)
            time.sleep(.1) #nap...
            return True
        except serial.serialutil.SerialException as e:
            log("Device {0} @ {1}: Error ({2}) {3}".format(
                self.config['serial_port'], self.config['serial_baud'],
                e.errno, e.strerror) )
            return False

    def serial_ready(self):
      def ready():
		if hasattr(self, 'ser'):
			return self.ser.writable() and self.ser.readable()
		else:
			return False;
      def init_and_check():
          state=self.init_serial()
          return ready()
      if hasattr(self, 'ser'):
        if ready(): 
          return True
        else:
          init_and_check()
      else:
        init_and_check()
                    
    def write_serial(self, str):
      if self.serial_ready():
        try: 
          #log('Sending signal to bluetooth: ' + str)
          self.ser.write(str)
          self.ser.flush()
          return True
        except serial.serialutil.SerialException as e:
          log('Serial not available')
          return False

    def send_heartbeat(self):
      hbchar = 'H\r\n'
      def write_hb_char():
        if not self.write_serial(hbchar):
          #log('Cannot send heartbeat')
          self.init_serial()
      def read_input():
        try:
          data = self.ser.read(9999) # Read a lot of bytes
          #log('Received data ' + data) 
        except serial.serialutil.SerialException as e:
          log('Read Exception')
      while True:
        if self.serial_ready():
          read_input()
          write_hb_char()
        time.sleep(2)

    def open_door(self, test=True):
        if test:
            str = 'd\r\n'
        else:
            str = 'p\r\n'
        return self.write_serial(str)

    def __call__(self, environ, start_response):
      return self.application(environ, start_response)

class Gatekeeper(object):
    def __init__(self, serial, config):
        print config
        self.serial = serial
        self.AccountSid=os.environ['TwilioAccountSID'] 
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
              if self.serial.open_door(test=False):
                  print "opening"
                  r.reject("Busy") 
              else:
                  r.say("Unable to write to serial. BOOL!")
          elif self.check_authorized_caller(phoneNumber,True):
              #log("Testing door opening")
              if self.serial.open_door():
                  r.reject("Busy") 
              else:
                  r.say("Unable to write to serial")
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
            serial_port='/dev/rfcomm0'
            serial_baud=38400
            config={'serial_port': serial_port, 'serial_baud': serial_baud}
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
    bt_comm = Serialer(config)
    t = threading.Thread(target=bt_comm.send_heartbeat)
    t.setDaemon(True)
    t.start()
    web_app = Gatekeeper(bt_comm, config)
    return web_app

if __name__ == '__main__':
    web_app = make_app()
    from werkzeug.serving import run_simple
    print "Starting server..."
    run_simple('', 5000, web_app)
