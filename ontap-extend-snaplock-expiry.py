#!python3

import json
import requests
import datetime
import re
import argparse

import urllib3

version = 0.9

# Arguments Parsing
parser = argparse.ArgumentParser(description='Update Snaplock snapshot expiry time according to snapmirror labels')
parser.add_argument('--version', '-v', action='version', version='%(prog)s ' + str(version))
parser.add_argument('--simulate', '-s', dest="simulate", action="store_true", default=False, help="Simulate, don't apply expiry date change and report on what would be done")
parser.add_argument('--check', '-c', dest="check", action="store_true", default=False, help="Check current Snaplock expiry and return compliant/non-compliant/error for each system")
parser.add_argument('--max-expiry', '-m', dest="max_expiry", default=15768000, type=int, help="Maximum expiration time that can be set in seconds. Defaults to 15768000 (6 months)")
parser.add_argument('-k', dest="ignore_ssl", action="store_true", default=False, help="Ignore SSL errors")

args = parser.parse_args()

# Notify if we're running in simulate mode
if args.simulate:
    print("Running in simulate mode")

# If -k is used, ignore SSL warnings
if args.ignore_ssl:
    urllib3.disable_warnings()

# Read configuration file
with open('config.json','r') as configfile:
    config = json.load(configfile)

snapmirror_labels = config['labels-policies'].keys()

# Start connecting to configured systems
for system in config["systems"]:
    compliance="compliant"
    auth = (system["username"],system["password"])
    try:
        r = requests.get('https://%s/api/storage/volumes' % system["ip"], auth=auth, verify=not args.ignore_ssl)
    except requests.exceptions.SSLError:
        # Handle SSL exception
        if args.check:
            compliance="error"
            print('%s = %s' % (system["ip"],compliance))
            continue
        print("Certificate verification failed for %s. Use -k or add appropriate CA to system configuration" % system["ip"])
        continue
    except requests.exceptions.ConnectionError as e:
        # Handle other connection errors
        if args.check:
            compliance="error"
            print('%s = %s' % (system["ip"],compliance))
            continue
        print("Unable to connect to %s" % system["ip"])
        print(e)
        continue

    # Bail if for some reason we don't get code 200
    if r.status_code != 200:
        if args.check:
            compliance="error"
            print('%s = %s' % (system["ip"],compliance))
            continue

        print("Failed to connect to %s" % system["ip"])

    volumes = r.json()

    # Check all volumes in the systems for snaplock snapshots
    for volume in volumes['records']:
        if compliance!="compliant":
            break            
        volume_uuid = volume['uuid']

        # Get all snapshots
        s = requests.get('https://%s/api/storage/volumes/%s/snapshots' % (system["ip"],volume_uuid), auth=auth, verify=not args.ignore_ssl)
        if s.status_code != 200:
            compliance="error"
            if args.check:
                break
            exit("Failed to get snapshots for volume %s on %s" % (volume_uuid,system["ip"]))
        
        snapshots = s.json()

        # Check all snapshots in the volume
        for snapshot in snapshots['records']:
            snapshot_uuid = snapshot['uuid']

            # Get snapshot details
            t = requests.get('https://%s/api/storage/volumes/%s/snapshots/%s' % (system["ip"],volume_uuid,snapshot_uuid), auth=auth, verify=not args.ignore_ssl)
            
            if t.status_code != 200:
                compliance="error"
                if args.check:
                    break
                print("Failed to get snapshot %s for volume %s on %s" % (snapshot_uuid,volume_uuid,system["ip"]))
            
            snapshot_details = t.json()

            snapshot_name = snapshot_details['name']
            snapshot_svm = snapshot_details['svm']['name']
            snapshot_volume = snapshot_details['volume']['name']
            snapshot_create_time = snapshot_details['create_time']
            snapshot_snapmirror_label = 'snapmirror_label' in snapshot_details and snapshot_details['snapmirror_label'] or None
            snapshot_snaplock_expiry_time = 'snaplock_expiry_time' in snapshot_details and snapshot_details['snaplock_expiry_time'] or None
            
            # Helper functions
            def ontap_to_standard(date):
                return re.sub(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}):(\d{2})',r'\1\2',date)
            def standard_to_ontap(date):
                return re.sub(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2})(\d{2})',r'\1:\2',date)

            # Check if there is a snaplock expiry time and the snapmirror labl is in the configuration
            if snapshot_snapmirror_label in snapmirror_labels and snapshot_snaplock_expiry_time:
            
                # Convert create time to standard object
                # ONTAP dates are *almost* standard, it seems it uses [+/-]HH:MM instead of [+/-]HHMM for timezone specification
                standard_snapshot_create_time = ontap_to_standard(snapshot_create_time)
                snapshot_create_time_obj = datetime.datetime.strptime(standard_snapshot_create_time, '%Y-%m-%dT%H:%M:%S%z')

                # Add the desired amount of seconds to create_time to determine snaplock_expiry_time
                seconds=config['labels-policies'][snapshot_snapmirror_label]
                if seconds > args.max_expiry:
                    break
                snaplock_expiry_time_obj = snapshot_create_time_obj + datetime.timedelta(seconds=seconds)

                # If in check mode, just compare  and continue
                if args.check:
                    current_snaplock_expiry_time = ontap_to_standard(snapshot_snaplock_expiry_time)
                    current_snaplock_expiry_time_obj = datetime.datetime.strptime(current_snaplock_expiry_time, '%Y-%m-%dT%H:%M:%S%z')
                    if current_snaplock_expiry_time_obj < snaplock_expiry_time_obj:
                        compliance="non-compliant"
                        break
                    continue
                # Convert date back to ONTAP format
                standard_snaplock_expiry_time=datetime.datetime.strftime(snaplock_expiry_time_obj,'%Y-%m-%dT%H:%M:%S%z')
                snaplock_expiry_time = standard_to_ontap(standard_snaplock_expiry_time)

                # Extend Snaplock expiry time on snapshot
                data={'vserver':snapshot_svm,'volume':snapshot_volume,'snapshot':snapshot_name,'expiry-time':snaplock_expiry_time}
                try:
                    if args.simulate==False:
                        u = requests.post('https://%s/api/private/cli/snapshot/modify-snaplock-expiry-time' % (system["ip"]), json=data, auth=auth, verify=not args.ignore_ssl)
                        if u.status_code != 200:
                            print(u.json()['error']['message'])
                            raise Exception()
                except Exception as e:
                    print("Failed to update expiry-time %s on snapshot %s for volume %s on svm %s on %s" % (snaplock_expiry_time,snapshot_name,snapshot_volume,snapshot_svm,system["ip"]))
                else:
                    if args.simulate == False:
                        print("Updated expiry-time from %s to %s on snapshot %s for volume %s on svm %s on %s" % (snapshot_create_time,snaplock_expiry_time,snapshot_name,snapshot_volume,snapshot_svm,system["ip"]))
                    else:
                        print("Would update expiry-time from %s to %s on snapshot %s for volume %s on svm %s on %s" % (snapshot_create_time,snaplock_expiry_time,snapshot_name,snapshot_volume,snapshot_svm,system["ip"]))
        print('%s = %s' % (system["ip"],compliance))
