#!/var/www/buzzer/pythonws/prod/bin/python

# This is so we can properly suid

activate_this = './prod/bin/activate_this.py'
execfile(activate_this, dict(__file__=activate_this))

from flup.server.fcgi import WSGIServer
from handler import make_app

if __name__ == '__main__':
    application = make_app()
    WSGIServer(application).run()
