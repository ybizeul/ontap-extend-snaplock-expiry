## Introduction

`ontap-extend-snaplock-expiry` is used to extend Snaplock expiry time on a category of snapshots, based on their snapmirror labels.

When using Snapvault to backup data to a Snaplock aggregate, there is no option to make so the snapshots are individually snaplocked to the same date as the snapshot expiration time. As an effect, whatever the default Snaplock time for the volume is will be applied to incoming snapshots.

This can cause a problem with mixed retention times, like keeping 30 daily snapshots, and 14 weekly snapshots : we should set the volume default snaplock expiration to 14 weeks, but in this case, all the daily snapshots within the 14 weeks retention for the weeklies will be retained and eat up additional space.

Depending on the change rate, this can cause a significant storage over consumption.

```
usage: ontap-extend-snaplock-expiry.py [-h] [--version] [--config CONFIG] [--simulate] [--check] [--max-expiry MAX_EXPIRY] [-k]

Update Snaplock snapshot expiry time according to snapmirror labels

optional arguments:
  -h, --help            show this help message and exit
  --version, -v         show program's version number and exit
  --config CONFIG       Path to configuration file. Defaults to ./config.json
  --simulate, -s        Simulate, don't apply expiry date change and report on what would be done
  --check, -c           Check current Snaplock expiry and return compliant/non-compliant/error for each system
  --max-expiry MAX_EXPIRY, -m MAX_EXPIRY
                        Maximum expiration time that can be set in seconds. Defaults to 15768000 (6 months)
  -k                    Ignore SSL errors
```

## Configuring snaplock extension time

Example configuration file :

```
{
    "systems":[
        {
            "ip":"cluster1.lab.tynsoe.org",
            "username":"admin",
            "password-base64": "TmV0YXBwMDE="
        },
        {
            "ip":"cluster2.lab.tynsoe.org",
            "username":"admin",
            "password":"Netapp01"
        }
    ],
    "labels-policies":{
        "slc_5min": 3600,
        "slc_1min": 300,
        "daily": 86400
    }
}
```

Set `insecure-ssl` to true if using self signed certificate for HTTPS.

### Certificate-based authentication

Instead of using username/password, you can authenticate using client certificates (mutual TLS). Add `certificate` and `key` fields to a system entry, pointing to the PEM-encoded client certificate and private key files respectively. When present, these override `username`/`password`/`password-base64`.

```
{
    "systems":[
        {
            "ip":"cluster1.lab.tynsoe.org",
            "certificate":"/path/to/client_cert.pem",
            "key":"/path/to/client_key.pem"
        }
    ],
    "labels-policies":{
        "daily": 86400
    }
}
```

The ONTAP cluster must be configured for certificate authentication. Refer to the ONTAP documentation for `security login create -authentication-method cert` and `security certificate install -type client-ca`.

Note that the `-k` flag still controls server certificate verification independently of client certificate authentication.

Configuration of the amount of time to lock a given snapshot is configured in `labels-policies`.

This is a key/value dictionary with the snapmirror label as a key, and an expiration time expressed in seconds for the corresponding snapshots.

In the example above, any snapshots with the `slc_5min` snapmirror label will have their snaplock expiration time set to `create_time + 3600s`

It is recommended to do a first run with `-s` argument to get an idea of what would be performed beforehand.

## Integration with SNMP

Add the following line in `/etc/snmp/snmpd.conf` to query compliance status through SNMP:

```
extend ontap-snaplock /opt/ontap-extend-snaplock-expiry.py --config /etc/ontap-snaplock.json -k -c
```

Sample output :

```
❯ snmpwalk -c public 192.168.64.12 NET-SNMP-EXTEND-MIB::nsExtendOutput2Table
NET-SNMP-EXTEND-MIB::nsExtendOutLine."ontap-snaplock".1 = STRING: cluster1.lab.tynsoe.org = compliant
NET-SNMP-EXTEND-MIB::nsExtendOutLine."ontap-snaplock".2 = STRING: cluster2.lab.tynsoe.org = error
NET-SNMP-EXTEND-MIB::nsExtendOutLine."ontap-snaplock".3 = STRING: cluster3.lab.tynsoe.org = non-compliant
```

## Collect snapshot capacity per labels

`ontap-sum-snapshot-delta.py` can be used to compile the cumulative capacity for every snapshot with a given snapmirror label.

```
usage: ontap-sum-snapshot-delta.py [-h] [--version] [--config CONFIG] [-k] [--debug]

Get snapshot deltas for a given label

options:
  -h, --help       show this help message and exit
  --version, -v    show program's version number and exit
  --config CONFIG  Path to configuration file. Defaults to ./config.json
  -k               Ignore SSL errors
  --debug, -d      Run in debug mode
```

## Network Requirements

|Source|Destination|Port|Description|
|------|-----------|----|-----------|
| Linux VM | ONTAP Management Interface | TCP/443 | ONTAP API communication |
| Monitoring server | Linux VM | UDP/161 | SNMP monitoring |
