# Spread Protocol #

Initial connect from client to server.

Client sends:
| Major Version Verion (4) | Minor Version (1) | Micro Version (0) | Notification (0x10 \| 0x01) | Client Name Length (NAMELEN) | Client Name |
|:-------------------------|:------------------|:------------------|:----------------------------|:-----------------------------|:------------|
| 1 byte | 1 byte | 1 byte | 1 byte | 1 byte | NAMELEN bytes |


Server sends:
| Auth Length (AUTHLEN) | Auth Types Supported, space delimited |
|:----------------------|:--------------------------------------|
| 1 byte | AUTHLEN bytes |

Client sends:
| Auth response |
|:--------------|
| 90 bytes |

Server sends: