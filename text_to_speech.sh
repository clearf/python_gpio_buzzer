#!/bin/bash

say() { local IFS=+;/usr/bin/mpg321 "http://translate.google.com/translate_tts?tl=en&q=$*"; }
say $*
