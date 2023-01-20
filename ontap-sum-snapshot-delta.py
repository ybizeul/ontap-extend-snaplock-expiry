#!/usr/bin/python

import logging
import sys
import json
import requests
import datetime
import re
import argparse
import xml.etree.ElementTree as ET

import urllib3

version = "0.9.0"

# Arguments Parsing
parser = argparse.ArgumentParser(description='Get snapshot deltas for a given label')
parser.add_argument('--version', '-v', action='version', version='%(prog)s ' + str(version))
parser.add_argument('--config', dest="config", action='store', default="config.json", help="Path to configuration file. Defaults to ./config.json")
parser.add_argument('-k', dest="ignore_ssl", action="store_true", default=False, help="Ignore SSL errors")
parser.add_argument('--debug', '-d', dest="debug", action="store_true", default=False, help="Run in debug mode")

args = parser.parse_args()

# Helper method to remove password from logs
def _protect(d):
    e = d.copy()
    if "password" in e:
        e['password'] = "<REDACTED>"
    return e
    
# Helper method to print to STDERR
def eprint(s):
    sys.stderr.write(s+"\n")

# Enable debug
if args.debug:
    logging.basicConfig(level=logging.DEBUG)

# If -k is used, ignore SSL warnings
if args.ignore_ssl:
    logging.debug("Disabling SSL warnings")
    urllib3.disable_warnings()

# Read configuration file
with open(args.config,'r') as configfile:
    logging.debug("Opening Configuration file %s" % args.config)
    config = json.load(configfile)

snapmirror_labels = config['labels-policies'].keys()
logging.debug("Snapmirror labels are {0}".format(", ".join(snapmirror_labels)))

ontapi_url = "/servlets/netapp.servlets.admin.XMLrequest_filer"
ontapi_snapshots_list = """<?xml version="1.0" encoding="UTF-8"?>
<netapp  xmlns="http://www.netapp.com/filer/admin" version="1.170">
  <snapshot-get-iter>
    <desired-attributes>
      <snapshot-info>
        <name></name>
        <volume></volume>
        <volume-provenance-uuid></volume-provenance-uuid>
        <vserver></vserver>
      </snapshot-info>
    </desired-attributes>
    <max-records>8192</max-records>
    <query>
      <snapshot-info>
        <snapmirror-label>{0}</snapmirror-label>
      </snapshot-info>
    </query>
    <tag></tag>
  </snapshot-get-iter>
</netapp>
"""

ontapi_snapshots_delta="""<?xml version="1.0" encoding="UTF-8"?>
<netapp  xmlns="http://www.netapp.com/filer/admin" version="1.170" vfiler="{0}">
  <snapshot-delta-info>
    <snapshot1>{1}</snapshot1>
    <snapshot2>{2}</snapshot2>
    <volume>{3}</volume>
  </snapshot-delta-info>
</netapp>
"""

# Start connecting to configured systems
for system in config["systems"]:
    logging.debug("Checking system '%s'" % json.dumps(_protect(system)))

    auth = (system["username"],system["password"])
    snapshots = {}
    try:
        url = 'https://%s%s' % (system["ip"],ontapi_url)
        logging.debug("API CALL : %s",url)
        for l in config["labels-policies"].keys():
            data = ontapi_snapshots_list.format(l)
            r = requests.post(url, data=data, auth=auth, verify=not args.ignore_ssl)
            logging.debug("Raw snapshots list: {0}".format(r.content))
            root = ET.fromstring(r.content)
            for s in root.findall(".//{http://www.netapp.com/filer/admin}snapshot-info"):
                volume = s.find("{http://www.netapp.com/filer/admin}volume").text
                vserver = s.find("{http://www.netapp.com/filer/admin}vserver").text
                name = s.find("{http://www.netapp.com/filer/admin}name").text
                if vserver not in snapshots:
                    snapshots[vserver] = {}
                if volume not in snapshots[vserver]:
                    snapshots[vserver][volume] = {}
                if l not in snapshots[vserver][volume]:
                    snapshots[vserver][volume][l] = []
                snapshots[vserver][volume][l].append(name)
    except requests.exceptions.SSLError:
        # Handle SSL exception
        eprint("Certificate verification failed for %s. Use -k or add appropriate CA to system configuration" % system["ip"])
        continue
    except requests.exceptions.ConnectionError as e:
        # Handle other connection errors
        if args.check:
            compliance="error"
            print(compliance)
            continue
        eprint("Unable to connect to %s" % system["ip"])
        eprint(e)
        continue

    logging.debug("Parsed Snapshots : {0}".format(snapshots))

    print("{0}\t{1}\t{2}\t{3}".format("Vserver","Volume","Label","Count","Size"))

    for vserver in snapshots:
        logging.debug("Vserver: %s" % vserver)
        for volume in snapshots[vserver]:
            logging.debug("Volume: %s" % volume)
            for label in snapshots[vserver][volume]:
                logging.debug("Label: %s" % label)
                snap = sorted(snapshots[vserver][volume][label])
                logging.debug("Snapshots: %s" % snap)

                l = len(snap)
                if l < 2:
                    continue
                size=0
                for i in range(l-1):
                    data = ontapi_snapshots_delta.format(vserver,snap[i],snap[i+1],volume)
                    r = requests.post(url, data=data, auth=auth, verify=not args.ignore_ssl)
                    """
                    <?xml version='1.0' encoding='UTF-8' ?>
                    <!DOCTYPE netapp SYSTEM 'file:/etc/netapp_gx.dtd'>
                    <netapp version='1.170' xmlns='http://www.netapp.com/filer/admin'>
                    <results status="passed"><consumed-size>393216</consumed-size><elapsed-time>86400</elapsed-time></results></netapp>%
                    """
                    root = ET.fromstring(r.content)
                    size = size + int(root.find(".//{http://www.netapp.com/filer/admin}consumed-size").text)

                print("{0}\t{1}\t{2}\t{3}\t{4}".format(vserver,volume,label,l,size))
                
