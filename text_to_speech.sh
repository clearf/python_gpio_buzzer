#!/bin/bash

say() { local IFS=+;/usr/bin/mpg321 "http://translate.google.com/translate_tts?ie=UTF-8&tl=en&q=$*"; }
say $*
