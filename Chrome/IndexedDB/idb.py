import plyvel
import comparator
import hashlib
import sys
from Crypto.Cipher import AES
def cmpr(a,b):
    return comparator.Compare(a,b,False)

if len(sys.argv)>1: 
  lcmp=sys.argv[1]
else:
  print("Needs path to IDB folder")
  sys.exit(1)
  
db = plyvel.DB(lcmp,comparator=cmpr, comparator_name=b'idb_cmp1')

ipool=comparator.IndexedPool()

def tst():                
 for key, value in db:
     ipool.ProcessKeyValue(key,value)

#import cProfile
tst()
for dbn in ipool.databases:
    print("Database: {}".format(ipool.databases[dbn].name))
    for os in ipool.databases[dbn].objectStores:
        print("OS:{}  {}".format(os,ipool.databases[dbn].objectStores[os].name))
        ostor=ipool.databases[dbn].objectStores[os]

db.close()
