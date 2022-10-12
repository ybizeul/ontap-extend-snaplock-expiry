## Introduction

`ontap-extend-snaplock-expiry` is used to extend Snaplock expiry time on a category of snapshots, based on their snapmirror labels.

When using Snapvault to backup data to a Snaplock aggregate, there is no option to make so the snapshots are individually snaplocked to the same date as the snapshot expiration time. As an effect, whatever the default Snaplock time for the volume is will be applied to incoming snapshots.

This can cause a problem with mixed retention times, like keeping 30 daily snapshots, and 14 weekly snapshots : we should set the volume default snaplock expiration to 14 weeks, but in this case, all the daily snapshots within the 14 weeks retention for the weeklies will be retained and eat up additional space.

Depending on the change rate, this can cause a significant storage consumption.

```
usage: ontap-extend-snaplock-expiry.py [-h] [--version] [--simulate] [--max-retention MAX_RETENTION] [-k]

Update Snaplock snapshot expiry time according to snapmirror labels

optional arguments:
  -h, --help            show this help message and exit
  --version, -v         show program's version number and exit
  --simulate, -s        Simulate, don't apply expiry date change and report on what would be done
  --max-retention MAX_RETENTION, -m MAX_RETENTION
                        Maximum retention time that can be set in seconds. Defaults to 15768000 (6 months)
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
            "password":"Netapp01"
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

Configuration of the amount of time to lock a given snapshot is configured in `labels-policies`.

This is a key/value dictionary with the snapmirror label as a key, and an expiration time for the corresponding snapshots in seconds.

In the example above, any snapshots with the `slc_5min` snapmirror label will have their snaplock expiration time set to `create_time + 3600s`

It is recommended to do a first run with `-s` argument to get an idea of what would be performed beforehand.