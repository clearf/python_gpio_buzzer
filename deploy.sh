#/bin/bash

# This is to copy thing over. In addition, to setup the virtualenv in our production space, do:
# virtualenv prod
# pip install -r requirements.txt (which lives in the repo but isn't copied)
# hg archive -I . -X "*.txt" -X "*.sh" /var/www/; sudo chown -R www-data:www-data /var/www/buzzer/*

git archive --format tar master | tar -xv -C /var/www/buzzer/pythonws/ 
sudo chown -R www-data:www-data /var/www/buzzer/*

# We've switched to git to deploy. 
sudo /etc/init.d/lighttpd restart
