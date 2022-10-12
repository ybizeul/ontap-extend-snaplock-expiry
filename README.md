## Abstract

`ontap-extend-snaplock-expiry` is used to extend Snaplock expiry time on a category of snapshots.

## Configuration

Example configuration file :

```
{
    "systems":[
        {
            "ip":"cluster1.lab.tynsoe.org",
            "username":"admin",
            "password":"Netapp01"
        }
    ],
    "labels-policies":{
        "slc_5min": 3600,
        "slc_1min": 300,
        "daily": 86400
    },
    "insecure-ssl": true
}
```

`labels-policies` : Dictionary describing the amount of seconds to extend the snaplock expiry time relative to the snapshot creation time.
`insecure-ssl` : Set to true if using self signed certificate.