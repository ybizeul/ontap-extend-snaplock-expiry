#!python

import logging
import sys
import json
import requests
import datetime
import re
import argparse
import base64

import urllib3

version = "1.0.0"

# Arguments Parsing
parser = argparse.ArgumentParser(description='Update Snaplock snapshot expiry time according to snapmirror labels')
parser.add_argument('--version', '-v', action='version', version='%(prog)s ' + str(version))
parser.add_argument('--config', dest="config", action='store', default="config.json", help="Path to configuration file. Defaults to ./config.json")
parser.add_argument('--simulate', '-s', dest="simulate", action="store_true", default=False, help="Simulate, don't apply expiry date change and report on what would be done")
parser.add_argument('--check', '-c', dest="check", action="store_true", default=False, help="Check current Snaplock expiry and return compliant/non-compliant/error for each system")
parser.add_argument('--max-expiry', '-m', dest="max_expiry", default=15768000, type=int, help="Maximum expiration time that can be set in seconds. Defaults to 15768000 (6 months)")
parser.add_argument('-k', dest="ignore_ssl", action="store_true", default=False, help="Ignore SSL errors")
parser.add_argument('--debug', '-d', dest="debug", action="store_true", default=False, help="Run in debug mode")

args = parser.parse_args()

# Helper method to remove password from logs
def _protect(d):
    e = d.copy()
    if "password" in e:
        e['password'] = "<REDACTED>"
    if "key" in e:
        e['key'] = "<REDACTED>"
    return e

# Helper method to print to STDERR
def eprint(s):
    sys.stderr.write(str(s)+"\n")

# Enable debug
if args.debug:
    logging.basicConfig(level=logging.DEBUG)

# Notify if we're running in simulate mode
if args.simulate:
    eprint("Running in simulate mode")

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

# Start connecting to configured systems
for system in config["systems"]:
    logging.debug("Checking system '%s'" % json.dumps(_protect(system)))

    compliance="compliant"

    if "certificate" in system:
        auth = None
        cert = (system["certificate"], system["key"])
        logging.debug("Using certificate-based authentication for %s" % system["ip"])
    elif "password-base64" in system:
        auth = (system["username"],base64.b64decode(system["password-base64"]))
        cert = None
    else:
        logging.warning("Password not base64-encoded in config file (%s)" % system["ip"])
        auth = (system["username"],system["password"])
        cert = None
    try:
        url = 'https://%s/api/storage/volumes?snaplock.type=compliance' % system["ip"]
        logging.debug("API CALL : %s",url)
        r = requests.get(url, auth=auth, cert=cert, verify=not args.ignore_ssl)
    except requests.exceptions.SSLError as e:
        # Handle SSL exception
        if args.check:
            compliance="error"
            print(compliance)
            continue
        eprint("Certificate verification failed for %s. Use -k or add appropriate CA to system configuration" % system["ip"])
        eprint(e)
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

    # Bail if for some reason we don't get code 200
    if r.status_code != 200:
        if args.check:
            compliance="error"
            print(compliance)
            continue

        eprint("Failed to connect to %s (Code %i : %s)" % (system["ip"],r.status_code,r.reason))
        continue

    volumes = r.json()
    logging.debug("Volumes : %s" % json.dumps(volumes))
    # Check all volumes in the systems for snaplock snapshots
    for volume in volumes['records']:
        logging.debug("Checking volume : %s" % json.dumps(volume))
        if compliance != "compliant":
            break            
        volume_uuid = volume['uuid']

        # Get all snapshots
        for label in snapmirror_labels:
            url = 'https://%s/api/storage/volumes/%s/snapshots?snapmirror_label=%s' % (system["ip"],volume_uuid,label)
            logging.debug("API CALL : %s",url)

            s = requests.get(url, auth=auth, cert=cert, verify=not args.ignore_ssl)
            if s.status_code != 200:
                compliance="error"
                if args.check:
                    break
                exit("Failed to get snapshots for volume %s on %s" % (volume_uuid,system["ip"]))
            
            snapshots = s.json()
            logging.debug("Snapshots : %s" % json.dumps(snapshots))

            # Check all snapshots in the volume
            for snapshot in snapshots['records']:
                logging.debug("Checking snapshot : %s" % json.dumps(snapshot))

                snapshot_uuid = snapshot['uuid']

                # Get snapshot details
                url = 'https://%s/api/storage/volumes/%s/snapshots/%s' % (system["ip"],volume_uuid,snapshot_uuid)
                logging.debug("API CALL : %s",url)

                t = requests.get(url, auth=auth, cert=cert, verify=not args.ignore_ssl)
                
                if t.status_code != 200:
                    compliance="error"
                    if args.check:
                        break
                    eprint("Failed to get snapshot %s for volume %s on %s" % (snapshot_uuid,volume_uuid,system["ip"]))
                
                snapshot_details = t.json()
                logging.debug("Snapshot details : %s",json.dumps(snapshot_details))

                snapshot_name = snapshot_details['name']
                snapshot_svm = snapshot_details['svm']['name']
                snapshot_volume = snapshot_details['volume']['name']
                snapshot_create_time = snapshot_details['create_time']
                snapshot_snapmirror_label = 'snapmirror_label' in snapshot_details and snapshot_details['snapmirror_label'] or None
                snapshot_snaplock_expiry_time = 'snaplock_expiry_time' in snapshot_details and snapshot_details['snaplock_expiry_time'] or None
                
                # Helper functions
                # For compatibility with Python 2.x missing %z in strptime, we are removing time zone data from the input.
                # Dismissing the time zone in the returned date should not have an impact, as by default the current system
                # time zone will be used.
                # We are leaving Python 3 lines commented out for documentation purpose.
                def ontap_to_standard(date):
                    return re.sub(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2}):(\d{2})',r'\1',date)
                    #return re.sub(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}):(\d{2})',r'\1\2',date) # Python 3
                def standard_to_ontap(date):
                    return date
                    #return re.sub(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2})(\d{2})',r'\1:\2',date) # Python 3

                # Check if there is a snaplock expiry time and the snapmirror labl is in the configuration
                if snapshot_snapmirror_label in snapmirror_labels and snapshot_snaplock_expiry_time:
                    logging.debug("Found matching label '%s'" % snapshot_snapmirror_label)
                    # Convert create time to standard object
                    # ONTAP dates are *almost* standard, it seems it uses [+/-]HH:MM instead of [+/-]HHMM for timezone specification
                    logging.debug("ontap snapshot_create_time : %s" % snapshot_create_time)
                    standard_snapshot_create_time = ontap_to_standard(snapshot_create_time)
                    logging.debug("standard_snapshot_create_time : %s" % standard_snapshot_create_time)

                    snapshot_create_time_obj = datetime.datetime.strptime(standard_snapshot_create_time, '%Y-%m-%dT%H:%M:%S')
                    #snapshot_create_time_obj = datetime.datetime.strptime(standard_snapshot_create_time, '%Y-%m-%dT%H:%M:%S%z') # Python 3

                    # Add the desired amount of seconds to create_time to determine snaplock_expiry_time
                    seconds=config['labels-policies'][snapshot_snapmirror_label]
                    # if seconds > args.max_expiry:
                    #     logging.debug("Configured duration for label is greater than MAX_EXPIRY, ignoring")
                    #     break
                    snaplock_expiry_time_obj = snapshot_create_time_obj + datetime.timedelta(seconds=seconds)

                    # If in check mode, just compare  and continue
                    
                    current_snaplock_expiry_time = ontap_to_standard(snapshot_snaplock_expiry_time)
                    current_snaplock_expiry_time_obj = datetime.datetime.strptime(current_snaplock_expiry_time, '%Y-%m-%dT%H:%M:%S')
                    # current_snaplock_expiry_time_obj = datetime.datetime.strptime(current_snaplock_expiry_time, '%Y-%m-%dT%H:%M:%S%z') # Python 3
                    logging.debug("Comparing %s and %s for volume %s" % (current_snaplock_expiry_time_obj,snaplock_expiry_time_obj,snapshot_volume))
                    if current_snaplock_expiry_time_obj < snaplock_expiry_time_obj:
                        if args.check:
                            compliance="non-compliant"
                            break
                    else:
                        continue
                        
                    # Verify we are not locking for a date in the future bigger than max_expiry
                    max_expiry = datetime.datetime.now() + datetime.timedelta(seconds=args.max_expiry)
                    if max_expiry < snaplock_expiry_time_obj:
                        logging.warning("Would set a date beyond max_expiry, ignoring")
                        continue

                    # Convert date back to ONTAP format
                    standard_snaplock_expiry_time=datetime.datetime.strftime(snaplock_expiry_time_obj,'%Y-%m-%dT%H:%M:%S')
                    #standard_snaplock_expiry_time=datetime.datetime.strftime(snaplock_expiry_time_obj,'%Y-%m-%dT%H:%M:%S%z') # Python 3
                    snaplock_expiry_time = standard_to_ontap(standard_snaplock_expiry_time)

                    # Extend Snaplock expiry time on snapshot
                    data={'vserver':snapshot_svm,'volume':snapshot_volume,'snapshot':snapshot_name,'expiry-time':snaplock_expiry_time}
                    if args.simulate == False:
                        try:
                            logging.debug("Calling /api/private/cli/snapshot/modify-snaplock-expiry-time with data : %s",json.dumps(data))
                            u = requests.post('https://%s/api/private/cli/snapshot/modify-snaplock-expiry-time' % (system["ip"]), json=data, auth=auth, cert=cert, verify=not args.ignore_ssl)
                            set_exp_out = u.json()
                            logging.debug("Set Expiry Time Result : %s" % json.dumps(set_exp_out))
                            if u.status_code != 200:
                                eprint(u.json()['error']['message'])
                                raise Exception()
                        except Exception as e:
                            eprint("Failed to update expiry-time %s on snapshot %s for volume %s on svm %s on %s" % (snaplock_expiry_time,snapshot_name,snapshot_volume,snapshot_svm,system["ip"]))
                        else:
                            eprint("Set expiry-time from creation time %s to %s on snapshot %s for volume %s on svm %s on %s" % (snapshot_create_time,snaplock_expiry_time,snapshot_name,snapshot_volume,snapshot_svm,system["ip"]))
                    else:
                            eprint("Would set expiry-time from creation time %s to %s on snapshot %s for volume %s on svm %s on %s" % (snapshot_create_time,snaplock_expiry_time,snapshot_name,snapshot_volume,snapshot_svm,system["ip"]))
    if args.check:
        print("%s\t%s" % (system["ip"],compliance))
