
# (c) Copyright 2013, 2014, 2015 University of Manchester\

from License import create_lic
import sys

def generate_license_full (argv):
    #input file which sent by user, it contains his machine idenetitfications
    file_=argv[0]
    #outputfile which contains the Licence
    lic_file=argv[1]
    #key for encrypt and decrypt
    # this should be the same asw the one in Hydar gams lib file
    key=argv[2]
    file = open(file_, 'rb')
    machine_id=file.read()
    file.close()
    try:
        create_lic("ultimate", 100000, lic_file, key)
        print "Done ", lic_file , "is genrated"
    except Exception, e:
        print e.message


def generate_license (argv):
     try:
        lic_file=argv[0]
        key=argv[1].strip()
        print key
        create_lic("ultimate",  key, lic_file)
     except Exception, e:
        print e.message


if __name__ == "__main__":
   generate_license(sys.argv[1:])