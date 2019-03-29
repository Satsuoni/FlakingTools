#include "content/browser/indexed_db/indexed_db_leveldb_coding.h"

#include <iterator>
#include <limits>

#include "base/logging.h"
#include "base/strings/string16.h"
#include "base/strings/utf_string_conversions.h"
#include "base/sys_byteorder.h"

#include "content/common/indexed_db/indexed_db_key_path.h"
try:
    xrange
except NameError:
    xrange = range
try:
    cmp
except NameError:
    def cmp(a,b):
     return ((a>b)-(a<b))

"""
// LevelDB Coding Scheme
// =====================
//
// LevelDB stores key/value pairs. Keys and values are strings of bytes,
// normally of type std::string.
//
// The keys in the backing store are variable-length tuples with different
// types of fields. Each key in the backing store starts with a ternary
// prefix: (database id, object store id, index id). For each, 0 is reserved
// for metadata. See KeyPrefix::Decode() for details of the prefix coding.
//
// The prefix makes sure that data for a specific database, object store, and
// index are grouped together. The locality is important for performance:
// common operations should only need a minimal number of seek operations. For
// example, all the metadata for a database is grouped together so that
// reading that metadata only requires one seek.
//
// Each key type has a class (in square brackets below) which knows how to
// encode, decode, and compare that key type.
//
// Strings (origins, names, etc) are encoded as UTF-16BE.
//
//
// Global metadata
// ---------------
// The prefix is <0, 0, 0>, followed by a metadata type byte:
//
// <0, 0, 0, 0> => backing store schema version [SchemaVersionKey]
// <0, 0, 0, 1> => maximum allocated database [MaxDatabaseIdKey]
// <0, 0, 0, 2> => SerializedScriptValue version [DataVersionKey]
// <0, 0, 0, 3>
//   => Blob journal
//     The format of the journal is:
//         {database_id (var int), blobKey (var int)}*.
//     If the blobKey is kAllBlobsKey, the whole database should be deleted.
//     [BlobJournalKey]
// <0, 0, 0, 4> => Live blob journal; same format. [LiveBlobJournalKey]
// <0, 0, 0, 100, database id>
//   => Existence implies the database id is in the free list
//      [DatabaseFreeListKey]
// <0, 0, 0, 201, origin, database name> => Database id (int) [DatabaseNameKey]
//
//
// Database metadata: [DatabaseMetaDataKey]
// ----------------------------------------
// The prefix is <database id, 0, 0> followed by a metadata type byte:
//
// <database id, 0, 0, 0> => origin name
// <database id, 0, 0, 1> => database name
// <database id, 0, 0, 2> => IDB string version data (obsolete)
// <database id, 0, 0, 3> => maximum allocated object store id
// <database id, 0, 0, 4> => IDB integer version (var int)
// <database id, 0, 0, 5> => blob key generator current number
//
//
// Object store metadata: [ObjectStoreMetaDataKey]
// -----------------------------------------------
// The prefix is <database id, 0, 0>, followed by a type byte (50), then the
// object store id (var int), then a metadata type byte.
//
// <database id, 0, 0, 50, object store id, 0> => object store name
// <database id, 0, 0, 50, object store id, 1> => key path
// <database id, 0, 0, 50, object store id, 2> => auto increment flag
// <database id, 0, 0, 50, object store id, 3> => is evictable
// <database id, 0, 0, 50, object store id, 4> => last "version" number
// <database id, 0, 0, 50, object store id, 5> => maximum allocated index id
// <database id, 0, 0, 50, object store id, 6> => has key path flag (obsolete)
// <database id, 0, 0, 50, object store id, 7> => key generator current number
//
// The key path was originally just a string (#1) or null (identified by flag,
// #6). To support null, string, or array the coding is now identified by the
// leading bytes in #1 - see EncodeIDBKeyPath.
//
// The "version" field is used to weed out stale index data. Whenever new
// object store data is inserted, it gets a new "version" number, and new
// index data is written with this number. When the index is used for
// look-ups, entries are validated against the "exists" entries, and records
// with old "version" numbers are deleted when they are encountered in
// GetPrimaryKeyViaIndex, IndexCursorImpl::LoadCurrentRow and
// IndexKeyCursorImpl::LoadCurrentRow.
//
//
// Index metadata: [IndexMetaDataKey]
// ----------------------------------
// The prefix is <database id, 0, 0>, followed by a type byte (100), then the
// object store id (var int), then the index id (var int), then a metadata
// type byte.
//
// <database id, 0, 0, 100, object store id, index id, 0> => index name
// <database id, 0, 0, 100, object store id, index id, 1> => unique flag
// <database id, 0, 0, 100, object store id, index id, 2> => key path
// <database id, 0, 0, 100, object store id, index id, 3> => multi-entry flag
//
//
// Other object store and index metadata
// -------------------------------------
// The prefix is <database id, 0, 0> followed by a type byte. The object
// store and index id are variable length integers, the names are variable
// length strings.
//
// <database id, 0, 0, 150, object store id>
//   => existence implies the object store id is in the free list
//      [ObjectStoreFreeListKey]
// <database id, 0, 0, 151, object store id, index id>
//   => existence implies the index id is in the free list [IndexFreeListKey]
// <database id, 0, 0, 200, object store name>
//   => object store id [ObjectStoreNamesKey]
// <database id, 0, 0, 201, object store id, index name>
//   => index id [IndexNamesKey]
//
//
// Object store data: [ObjectStoreDataKey]
// ---------------------------------------
// The prefix is followed by a type byte and the encoded IDB primary key. The
// data has a "version" prefix followed by the serialized script value.
//
// <database id, object store id, 1, user key>
//   => "version", serialized script value
//
//
// "Exists" entry: [ExistsEntryKey]
// --------------------------------
// The prefix is followed by a type byte and the encoded IDB primary key.
//
// <database id, object store id, 2, user key> => "version"
//
//
// Blob entry table: [BlobEntryKey]
// --------------------------------
//
// The prefix is followed by a type byte and the encoded IDB primary key.
//
// <database id, object store id, 3, user key> => array of IndexedDBBlobInfo
//
//
// Index data
// ----------
// The prefix is followed by a type byte, the encoded IDB index key, a
// "sequence" number (obsolete; var int), and the encoded IDB primary key.
//
// <database id, object store id, index id, index key, sequence number,
//   primary key> => "version", primary key [IndexDataKey]
//
// The sequence number is obsolete; it was used to allow two entries with the
// same user (index) key in non-unique indexes prior to the inclusion of the
// primary key in the data.
//
// Note: In order to be compatible with LevelDB's Bloom filter each bit of the
// encoded key needs to used and "not ignored" by the comparator.
"""
import array
import ctypes

#using base::StringPiece;
#using blink::WebIDBKeyType;
#using blink::WebIDBKeyTypeArray;
#using blink::WebIDBKeyTypeBinary;
#using blink::WebIDBKeyTypeDate;
#using blink::WebIDBKeyTypeInvalid;
#using blink::WebIDBKeyTypeMin;
#using blink::WebIDBKeyTypeNull;
#using blink::WebIDBKeyTypeNumber;
#using blink::WebIDBKeyTypeString;
#using blink::WebIDBKeyPathType;
#using blink::WebIDBKeyPathTypeArray;
#using blink::WebIDBKeyPathTypeNull;
#using blink::WebIDBKeyPathTypeString;

kDefaultInlineBufferSize = 32


kIndexedDBKeyNullTypeByte = 0
kIndexedDBKeyStringTypeByte = 1
kIndexedDBKeyDateTypeByte = 2;
kIndexedDBKeyNumberTypeByte = 3;
kIndexedDBKeyArrayTypeByte = 4;
kIndexedDBKeyMinKeyTypeByte = 5;
kIndexedDBKeyBinaryTypeByte = 6;

kIndexedDBKeyPathTypeCodedByte1 = 0;
kIndexedDBKeyPathTypeCodedByte2 = 0;

kObjectStoreDataIndexId = 1;
kExistsEntryIndexId = 2;
kBlobEntryIndexId = 3;

kSchemaVersionTypeByte = 0
kMaxDatabaseIdTypeByte = 1
kDataVersionTypeByte = 2
kBlobJournalTypeByte = 3
kLiveBlobJournalTypeByte = 4
kEarliestSweepTimeTypeByte = 5 
kMaxSimpleGlobalMetaDataTypeByte =6  #Insert before this and increment.
kDatabaseFreeListTypeByte = 100
kDatabaseNameTypeByte = 201

kObjectStoreMetaDataTypeByte = 50
kIndexMetaDataTypeByte = 100
kObjectStoreFreeListTypeByte = 150
kIndexFreeListTypeByte = 151
kObjectStoreNamesTypeByte = 200
kIndexNamesKeyTypeByte = 201

kObjectMetaDataTypeMaximum = 255
kIndexMetaDataTypeMaximum = 255
kMinimumIndexId = 30


#WebIDBKeyTypeArray = 1
#WebIDBKeyTypeBinary = 2
#WebIDBKeyTypeString =3
#WebIDBKeyTypeDate =4 
#WebIDBKeyTypeNumber =5 
#WebIDBKeyTypeNull =6 
#WebIDBKeyTypeInvalid =7
#WebIDBKeyTypeMin =8

WebIDBKeyTypeInvalid = 0
WebIDBKeyTypeArray =1
WebIDBKeyTypeBinary =2
WebIDBKeyTypeString =3 
WebIDBKeyTypeDate =4
WebIDBKeyTypeNumber =5 
WebIDBKeyTypeNull=6
WebIDBKeyTypeMin=7


WebIDBKeyPathTypeNull = 0 
WebIDBKeyPathTypeString =1
WebIDBKeyPathTypeArray=2

WebIDBDataLossNone = 0 
WebIDBDataLossTotal =1


"""
enum WebIDBCursorDirection {
    WebIDBCursorDirectionNext = 0,
    WebIDBCursorDirectionNextNoDuplicate = 1,
    WebIDBCursorDirectionPrev = 2,
    WebIDBCursorDirectionPrevNoDuplicate = 3,
    WebIDBCursorDirectionLast = WebIDBCursorDirectionPrevNoDuplicate
};
enum WebIDBTaskType {
    WebIDBTaskTypeNormal = 0,
    WebIDBTaskTypePreemptive,
    WebIDBTaskTypeLast = WebIDBTaskTypePreemptive
};
enum WebIDBPutMode {
    WebIDBPutModeAddOrUpdate,
    WebIDBPutModeAddOnly,
    WebIDBPutModeCursorUpdate,
    WebIDBPutModeLast = WebIDBPutModeCursorUpdate
};
enum WebIDBTransactionMode {
    WebIDBTransactionModeReadOnly = 0,
    WebIDBTransactionModeReadWrite,
    WebIDBTransactionModeVersionChange,
    WebIDBTransactionModeLast = WebIDBTransactionModeVersionChange
};
"""


#into is a list, I guess? array
def EncodeIntSafely(value, mx, into):
  #DCHECK_LE(value, max);
  if value > mx: raise ValueError("{} greater than {}!".format(value,mx))
  return EncodeInt(value, into);


def MaxIDBKey() :
  ret=array.array('B')
  EncodeByte(kIndexedDBKeyNullTypeByte, ret)
  return ret


def MinIDBKey() :
  ret=array.array('B')
  EncodeByte(kIndexedDBKeyMinKeyTypeByte, ret)
  return ret


def EncodeByte(value,  into):
  into.append(value)


def EncodeBool( value,  into):
  into.append(1 if value else 0)


def EncodeInt( value, into) :
  n = ctypes.c_uint64(value).value
  into.append(n&255)
  n =(n >> 8)
  while n>0:
    into.append(n&255)
    n =(n >> 8)
    
 

def EncodeVarInt( value, into) :
  n = ctypes.c_uint64(value).value
  c=(n&127)
  n=n>>7
  if n!=0:
    c=(c|0x80)
  into.append(c)
  while n>0:
      c=(n&127)
      n=(n>>7)
      if n!=0:
        c=(c|0x80)
      into.append(c)

#our strings are utf8?
#use utf16-be

def EncodeString(value,  into):
  if len(value)==0: return
  try:
      dat=value.encode("utf-16be")
  except:
      print ("Invalid string!")
      return  
  for u in dat:
      into.append(ord(u))        
  #// Backing store is UTF-16BE, convert from host endianness.
  #size_t length = value.length();
  #size_t current = into->size();
  #into->resize(into->size() + length * sizeof(base::char16));
  #const base::char16* src = value.c_str();
  #base::char16* dst =
  #    reinterpret_cast<base::char16*>(&*into->begin() + current);
  #for (unsigned i = 0; i < length; ++i)
  #  *dst++ = htons(*src++);

import struct

def EncodeBinary( value,  into):
  EncodeVarInt( len(value), into)
  for u in value:
      try:
       into.append(u)
      except:
       into.append(ord(u))


def EncodeStringWithLength(value, into):
  EncodeVarInt(len(value)/2, into)
  EncodeString(value, into)

def EncodeDouble( value,into) :
  packed = struct.pack('d', value)
  for u in packed:
      try:
       into.append(ord(u))   
      except:
       into.append(u)
class IndexedDBKey:
    ctype=WebIDBKeyTypeNull
    #array list
    #binary str
    #string utf16be
    #date double
    #number double
    def __init__(self):
        self.ctype=WebIDBKeyTypeNull
        self.binary=None
        self.array=None
        self.date=None
        self.string=None
        self.number=None
    def getVal(self):
        if self.ctype==WebIDBKeyTypeNull: return None
        if self.ctype==WebIDBKeyTypeBinary: return self.binary
        if self.ctype==WebIDBKeyTypeString: return self.string
        if self.ctype==WebIDBKeyTypeDate: return self.date
        if self.ctype==WebIDBKeyTypeNumber: return self.number
        if self.ctype==WebIDBKeyTypeArray:
             ret=[]
             if self.array is None: return None
             for itm in self.array:
                 ret.append(itm.getVal)
             return ret    
    def __hash__(self):
          if self.ctype==WebIDBKeyTypeNull: return 0
          if self.ctype==WebIDBKeyTypeArray:      
              arr='_'.join([str(k.__hash__()) for k in self.getVal()])
              return arr.__hash__()
          return  self.getVal().__hash__()
    def __eq__(self, other):
        if self.ctype==WebIDBKeyTypeNull and other.ctype==WebIDBKeyTypeNull:
            return True
        if self.ctype==WebIDBKeyTypeArray:    
            a1=self.getVal()
            a2=other.getVal()
            if len(a1)!=len(a2): return False
            for i in xrange(len(a1)):
                if a1[i]!=a2[i]:
                    return False
            return True              
        return self.getVal() == other.getVal()
    def __ne__(self, other):
        # Not strictly necessary, but to avoid having both x==y and x!=y
        # True at the same time
        return not(self == other)              
    def __repr__(self):
        ctp=self.ctype
        if ctp==KeyTypeByteToKeyType(kIndexedDBKeyNullTypeByte) or ctp== KeyTypeByteToKeyType(kIndexedDBKeyMinKeyTypeByte): return "IndexedDBKey: Null"
        if ctp==KeyTypeByteToKeyType(kIndexedDBKeyArrayTypeByte):
            ret==u"IndexedDBKey: ["
            for pos in range(len(self.array)):
                ret=ret+repr(self.array[pos])+" , "
            ret=ret+u"]"
            return ret    
        if ctp==KeyTypeByteToKeyType( kIndexedDBKeyBinaryTypeByte):
            return u"IndexedDBKey: "+str(self.binary)
        if ctp==  KeyTypeByteToKeyType( kIndexedDBKeyStringTypeByte):
            return u"IndexedDBKey: (string)"+self.string#.encode("utf-16be")
            
        if ctp==KeyTypeByteToKeyType( kIndexedDBKeyDateTypeByte):
             return u"IndexedDBKey: (date) "+str(self.date)
        if ctp==KeyTypeByteToKeyType( kIndexedDBKeyNumberTypeByte):
             return u"IndexedDBKey: (number) "+str(self.number)
        return "Improp_Typed_{}".format(ctp)     

def EncodeIDBKey( value, into):
  previous_size = len(into);
  #DCHECK(value.IsValid());
  if value.ctype==WebIDBKeyTypeArray:
      EncodeByte(kIndexedDBKeyArrayTypeByte, into)
      length = len(value.array)
      EncodeVarInt(length, into)
      for key in value.array:
          EncodeIDBKey(key, into)
      return
  elif value.ctype==WebIDBKeyTypeBinary:
      EncodeByte(kIndexedDBKeyBinaryTypeByte, into)
      EncodeBinary(value.binary, into)
      return
  elif value.ctype==WebIDBKeyTypeString:                       
      EncodeByte(kIndexedDBKeyStringTypeByte, into)
      EncodeStringWithLength(value.string, into) 
      return
  elif value.ctype==WebIDBKeyTypeDate:    
      EncodeByte(kIndexedDBKeyDateTypeByte, into)
      EncodeDouble(value.date, into)
      return
  elif value.ctype==WebIDBKeyTypeNumber:
      EncodeByte(kIndexedDBKeyNumberTypeByte, into);
      EncodeDouble(value.number, into);
      return
  else:
     print ("Unreached" )
     EncodeByte(kIndexedDBKeyNullTypeByte, into)
     return      

class IndexedDBKeyPath:
  def __init__( self):
      self.string=""
      self.array=[]
      self.ctype=WebIDBKeyPathTypeNull
def EncodeIDBKeyPath( value, into):
  #May be typed, or may be a raw string. An invalid leading
  #byte is used to identify typed coding. New records are
  #always written as typed.
  EncodeByte(kIndexedDBKeyPathTypeCodedByte1, into)
  EncodeByte(kIndexedDBKeyPathTypeCodedByte2, into)
  EncodeByte(value.type, into)
  if value.ctype==WebIDBKeyPathTypeNull:
      pass
  elif value.ctype==WebIDBKeyPathTypeString:
      EncodeStringWithLength(value.string, into)
  elif  value.ctype==WebIDBKeyPathTypeArray:
      count=len(value.array)
      EncodeVarInt(count, into)
      for val in value.array:
          EncodeStringWithLength(val, into)

#BlobJournal is a map

def EncodeBlobJournal( journal,  into):
  for key in journal:
      val=journal[key]
      EncodeVarInt(key, into)
      EncodeVarInt(val, into)  

def DecodeByte(slc):
    if len(slc)==0: return (False,None)
    value=slc.pop(0)
    return (True,value)
    
    
def DecodeBool(slc):
    if len(slc)==0: return (False,None)
    value=not (not slc.pop(0))
    return (True,value)

def DecodeInt(slc):
    if len(slc)==0: return (False,None)
    shift = 0
    ret = 0    
    for val in slc:
        ret = ret| (val << shift)
        shift=shift+8
    while len(slc)>0 : slc.pop()    
    return (True,ret)  
      
def DecodeVarInt(slc):
    if len(slc)==0: return (False,None)
    shift=0
    ret=0
    
    c=slc.pop(0)
    ret = ret| ((c&0x7f)<<shift)
    shift= shift + 7
    while (c&0x80)>0:
         c=slc.pop(0)
         ret = ret| ((c&0x7f)<<shift)
         shift= shift + 7 
    return (True,ret)
def hexbin(slc):
    ret=""
    for i in slc:
     ret=ret+"%02x" %(i,)
    return ret 
def DecodeString(slc):
    if len(slc)==0: return (True,"")
    if(len(slc)%2)!=0: return (False,None)
    decoded=slc.tostring().decode("utf-16be")
    #print (u"Decoded"+hexbin(slc))
    while len(slc)>0 : slc.pop() 
    return (True,decoded)

def DecodeStringWithLength(slc):
    if len(slc)==0: return (False,None)
    (res,length)=DecodeVarInt(slc)
    if not res or length<0: return (False, None)
    bts=length*2
    if (len(slc)<bts): return (False, None)
    (res,ret)=DecodeString(slc[:bts])
    for a in xrange(bts): slc.pop(0) 
    if not res: return (False, None)
    return (True, ret)
    
def DecodeBinary(slc):
    if len(slc)==0: return (False,None)
    (res,length)=DecodeVarInt(slc)
    if not res or length<0: return (False, None)
    if len(slc)<length: return (False,None)
    ret=slc[:length]
    for a in xrange(length): slc.pop(0)
    return (True, ret)
    
def DecodeIDBKey(slc):
    if len(slc)==0: return (False,None)
    ctype=slc.pop(0)
    if ctype==kIndexedDBKeyNullTypeByte:
        return (True,IndexedDBKey())
    elif  ctype== kIndexedDBKeyArrayTypeByte:
        (res,length)=DecodeVarInt(slc)
        if not res or length<0: return (False, None)
        arr=[]
        for x in xrange(length):
            (res,key)=DecodeIDBKey(slc)
            if not res: return (False,None)
            arr.append(key)
        ret= IndexedDBKey() 
        ret.ctype=WebIDBKeyTypeArray
        ret.array=arr
        return (True,ret)
    elif ctype== kIndexedDBKeyBinaryTypeByte: 
        (res,binr)=DecodeBinary(slc)
        if not res: return (False,None)
        ret= IndexedDBKey() 
        ret.ctype=WebIDBKeyTypeBinary
        ret.binary=binr
        return (True,ret)     
    elif ctype== kIndexedDBKeyStringTypeByte:
        (res,st)=DecodeStringWithLength(slc)
        if not res: return (False,None)
        ret= IndexedDBKey() 
        ret.ctype=WebIDBKeyTypeString
        ret.string=st
        return (True,ret)          
    elif ctype==kIndexedDBKeyDateTypeByte:
        (res,dt)=DecodeDouble(slc)
        if not res: return (False,None)
        ret= IndexedDBKey() 
        ret.ctype=WebIDBKeyTypeDate
        ret.date=dt
        return (True,ret)   
    elif ctype==kIndexedDBKeyNumberTypeByte:
        (res,dt)=DecodeDouble(slc)
        if not res: return (False,None)
        ret= IndexedDBKey() 
        ret.ctype=WebIDBKeyTypeNumber
        ret.number=dt
        return (True,ret)   
    else:
        print ("UnreachedDecode")
        return (False,None)     
             
dleng = len(struct.pack('d', 0))
def DecodeDouble(slc):
    if len(slc)<dleng: return (False, None)
    ret=struct.unpack('d',slc[:dleng])[0]
    for a in xrange(dleng): slc.pop(0)
    return (True,ret)

def DecodeIDBKeyPath(slc):
    if len(slc)<3 or (slc[0]!=kIndexedDBKeyPathTypeCodedByte1) or (slc[1]!=kIndexedDBKeyPathTypeCodedByte2):
        (res,st)=DecodeString(slc)
        if not res: return (False,None)
        ret=IndexedDBKeyPath()
        ret.ctype=WebIDBKeyPathTypeString
        ret.string=st
        return (True,ret)
    slc.pop(0)
    slc.pop(0)
    if len(slc)==0: return (False, None)    
    ctype=slc.pop(0)
    if ctype==WebIDBKeyPathTypeNull:
        ret=IndexedDBKeyPath()
        return (True,ret)
    elif ctype==  WebIDBKeyPathTypeString:
        (res,st)=  DecodeStringWithLength(slc)
        if not res: return (False,None)
        ret=IndexedDBKeyPath()
        ret.ctype=WebIDBKeyPathTypeString
        ret.string=st
        return (True,ret)
    elif ctype==WebIDBKeyPathTypeArray:
        (res,count)=DecodeVarInt(slc)
        if not res or count <0: return (False,None)  
        arr=[]
        for x in xrange(count):
            (res,st)=  DecodeStringWithLength(slc)
            if not res: return (False,None)
            arr.append(st)
        ret=IndexedDBKeyPath()
        ret.ctype=WebIDBKeyPathTypeArray
        ret.array=arr
        return (True,ret)        
        
    else:
       print ("ErrorPathDec")
       return (False,None)

def DecodeBlobJournal(slc):
    ret={}
    while len(slc)>0:
        did=-1
        bk=-1
        (res, did)=DecodeVarInt(slc)
        if not res or did<0: return (False,None)
        (res,bk)=DecodeVarInt(slc)
        if not res or bk<0: return (False,None)
        ret[did]=bk #maybe they are pairs? Later...
    return (True,ret)

def   ConsumeEncodedIDBKey(slc):
    (res,usl)=DecodeIDBKey(slc) 
    return res
        
def ExtractEncodedIDBKey(slc):
    (res,usl)=DecodeIDBKey(slc)
    if not res: return (False,None)
    renc=array.array('B')
    EncodeIDBKey(usl,renc)
    return renc


def  KeyTypeByteToKeyType(ctype):
    if ctype==kIndexedDBKeyNullTypeByte:
        return WebIDBKeyTypeInvalid
    if ctype==kIndexedDBKeyArrayTypeByte:
        return WebIDBKeyTypeArray
    if ctype==kIndexedDBKeyBinaryTypeByte:
        return WebIDBKeyTypeBinary
    if ctype==kIndexedDBKeyStringTypeByte:
        return WebIDBKeyTypeString
    if ctype==kIndexedDBKeyDateTypeByte:
        return WebIDBKeyTypeDate
    if ctype==kIndexedDBKeyNumberTypeByte:
        return WebIDBKeyTypeNumber
    if ctype==kIndexedDBKeyMinKeyTypeByte:
        return WebIDBKeyTypeMin
    print ("NotReached")
    return WebIDBKeyTypeInvalid

def CompareEncodedStringsWithLength(slc1,slc2):
    (res,st1)=DecodeStringWithLength(slc1)
    if not res: return (False,0)
    (res,st2)=DecodeStringWithLength(slc2)
    if not res: return (False,0)
    return cmp(st1,st2)

def CompareEncodedBinary(slc1,slc2):
    (res,st1)=DecodeBinary(slc1)
    if not res: return (False,0)
    (res,st2)=DecodeBinary(slc2)
    if not res: return (False,0)
    return cmp(st1,st2)        
    
def CompareInts(a, b):
  diff = a - b
  if (diff < 0):
    return -1
  if (diff > 0):
    return 1
  return 0

def CompareSizes(a, b):
  return cmp (a,b)


def CompareTypes( a,  b):
    return cmp(a,b)

def CompareDecodedIDBKeys(key1,key2):
    if key1.ctype!=key2.ctype: return CompareTypes(key1.ctype,key2.ctype)
    ctp=key1.ctype
    #print ctp
    if ctp==KeyTypeByteToKeyType(kIndexedDBKeyNullTypeByte) or ctp== KeyTypeByteToKeyType(kIndexedDBKeyMinKeyTypeByte): return (True,0)
    if ctp==KeyTypeByteToKeyType(kIndexedDBKeyArrayTypeByte):
        for pos in range(min(len(key1.array),len(key2.array))):
            (ok,res)=CompareDecodedIDBKeys(key1.array[pos],key2.array[pos])
            if not ok: return (False,0)
            if res!=0: return (True,res)
        return (True,cmp(len(key1.array),len(key2.array)))
    if ctp==KeyTypeByteToKeyType( kIndexedDBKeyBinaryTypeByte):
        return (True, cmp(key1.binary,key2.binary))
    if ctp==   KeyTypeByteToKeyType( kIndexedDBKeyStringTypeByte):
        return (True, cmp(key1.string,key2.string))
        
    if ctp==KeyTypeByteToKeyType( kIndexedDBKeyDateTypeByte):
        return (True,cmp(key1.date,key2.date))
    if ctp==KeyTypeByteToKeyType( kIndexedDBKeyNumberTypeByte):
        return (True,cmp(key1.number,key2.number))
    print ("NotReachedCompare")
    return (False,0)            
                
def CompareEncodedIDBKeys(slc1,slc2):
    (res,key1)=DecodeIDBKey(slc1)
    if not res: return (False,0)
    (res,key2)=DecodeIDBKey(slc2)
    if not res: return (False,0)
    return CompareDecodedIDBKeys(key1,key2)

    
class KeyPrefix(object):
   GLOBAL_METADATA=0
   DATABASE_METADATA =1
   OBJECT_STORE_DATA =2
   EXISTS_ENTRY =3
   INDEX_DATA =4 
   INVALID_TYPE =5
   BLOB_ENTRY =6
   kMaxDatabaseIdSizeBits = 3
   kMaxObjectStoreIdSizeBits = 3
   kMaxIndexIdSizeBits = 2
   kMaxDatabaseIdSizeBytes = (1 << kMaxDatabaseIdSizeBits)  # 8
   kMaxObjectStoreIdSizeBytes = (1 << kMaxObjectStoreIdSizeBits)#     // 8
   kMaxIndexIdSizeBytes = (1 << kMaxIndexIdSizeBits)  # 4
   kMaxDatabaseIdBits = (1 << kMaxIndexIdSizeBits) * 8 - 1 # 63
   kMaxObjectStoreIdBits = (1 << kMaxObjectStoreIdSizeBits) * 8 - 1#   // 63
   kMaxIndexIdBits = (1 << kMaxIndexIdSizeBits) * 8 - 1 # 31
   kMaxDatabaseId = (1 << kMaxDatabaseIdBits) - 1  
   kMaxObjectStoreId = (1 << kMaxObjectStoreIdBits) - 1
   kMaxIndexId = (1 << kMaxIndexIdBits) - 1
   kInvalidId = -1
  
   def __init__(self,dbId=-1,object_store_id=-1,index_id=-1):
      self.database_id=dbId
      self.object_store_id=object_store_id
      self.index_id =index_id

 # static KeyPrefix CreateWithSpecialIndex(int64 database_id,
 #                                         int64 object_store_id,
 #                                         int64 index_id);
  
  
  
   def Decode(self,slc):
      (res,first_byte)=DecodeByte(slc)
      if not res: return False
      database_id_bytes = ((first_byte >> 5) & 0x7) + 1
      object_store_id_bytes = ((first_byte >> 2) & 0x7) + 1
      index_id_bytes = (first_byte & 0x3) + 1
      if (database_id_bytes + object_store_id_bytes + index_id_bytes > len(slc)): return False
      tmp=slc[:database_id_bytes]
      (res,did)=DecodeInt(tmp)
      if not res:return False
      self.database_id=did
      for x in xrange(database_id_bytes): slc.pop(0)
      tmp=slc[:object_store_id_bytes]
      (res,osid)=DecodeInt(tmp)
      if not res:return False
      self.object_store_id=osid
      for x in xrange(object_store_id_bytes): slc.pop(0)
      tmp=slc[:index_id_bytes]
      (res,iid)=DecodeInt(tmp)
      if not res:return False
      self.index_id=iid
      for x in xrange(index_id_bytes): slc.pop(0)      
      return True
   def Encode(self):
       return EncodeInternal(self.database_id, self.object_store_id, self.index_id)
        
   def EncodeEmpty(self):
       return array.array('B',[0,0,0,0])
   def EncodeInternal(self, dbid,osid,iid):
       ret_did=array.array('B')
       EncodeInt(dbid,ret_did)
       ret_osid=array.array('B')
       EncodeInt(osid,ret_osid)
       ret_iid=array.array('B')
       EncodeInt(iid,ret_iid)
       first_byte = (len(ret_did) - 1) << (KeyPrefix.kMaxObjectStoreIdSizeBits + KeyPrefix.kMaxIndexIdSizeBits) | (len(ret_osid) - 1) << kMaxIndexIdSizeBits | (len(ret_iid) - 1)
       ret=  array.array('B',[first_byte])
       ret.expand(ret_did)
       ret.expand(ret_osid)
       ret.expand(ret_iid)
       return ret
   def  Compare(self,other):
        if(self.database_id!=other.database_id):
            return CompareInts(self.database_id,other.database_id)
        if self.object_store_id!=other.object_store_id:
             return  CompareInts(self.object_store_id,other.object_store_id)
        if self.index_id!=other.index_id:
             return  CompareInts(self.index_id,other.index_id)
        return 0  
   def __repr__(self):
     return "<Prefix_{}_{}_{}>".format(self.database_id,self.object_store_id,self.index_id)          
   def ctype(self):
        if not self.database_id:
            return KeyPrefix.GLOBAL_METADATA
        if not self.object_store_id:
            return KeyPrefix.DATABASE_METADATA
        if self.index_id==  kObjectStoreDataIndexId:
            return KeyPrefix.OBJECT_STORE_DATA   
        if self.index_id==  kExistsEntryIndexId:
            return KeyPrefix.EXISTS_ENTRY   
        if self.index_id==  kBlobEntryIndexId:
            return KeyPrefix.BLOB_ENTRY   
        if self.index_id >=  kMinimumIndexId:
            return KeyPrefix.INDEX_DATA       
        return KeyPrefix.INVALID_TYPE

#  CONTENT_EXPORT static bool IsValidDatabaseId(int64 database_id);
#  static bool IsValidObjectStoreId(int64 index_id);
#  static bool IsValidIndexId(int64 index_id);
#  static bool ValidIds(int64 database_id,
#                       int64 object_store_id,
#                       int64 index_id) {
#    return IsValidDatabaseId(database_id) &&
#           IsValidObjectStoreId(object_store_id) && IsValidIndexId(index_id);
#  }
#  static bool ValidIds(int64 database_id, int64 object_store_id) {
#    return IsValidDatabaseId(database_id) &&
#           IsValidObjectStoreId(object_store_id);
#  }

#  Type type() const;





def  CompareSuffix_ExistsEntryKey (slice_a,slice_b,only_compare_index_keys):
  return CompareEncodedIDBKeys(slice_a, slice_b)


def CompareSuffix_ObjectStoreDataKey(slice_a,slice_b,only_compare_index_keys):
  return CompareEncodedIDBKeys(slice_a, slice_b)


def CompareSuffix_BlobEntryKey(slice_a,slice_b,only_compare_index_keys):
  return CompareEncodedIDBKeys(slice_a, slice_b)

def CompareSuffix_IndexDataKey(slice_a,slice_b,only_compare_index_keys):
  (ok,res)=CompareEncodedIDBKeys(slice_a, slice_b)
  if not ok or res:
    return (ok,res)
  if (only_compare_index_keys):
    return (ok,0)
  (ok, sequence_number_a) = DecodeVarInt(slice_a)
  if not ok: return (True,0)
  (ok, sequence_number_b) = DecodeVarInt(slice_b)
  if not ok: return (True,0)
  if len(slice_a)==0 or len(slice_b)==0:
    return (True,CompareSizes(len(slice_a), len(slice_b)))
  (ok, result) = CompareEncodedIDBKeys(slice_a, slice_b)
  if not ok or result:
    return (ok,result)
  return (True,CompareInts(sequence_number_a, sequence_number_b))

def Compare_Bool( a,b, only_compare_index_keys):
  try:
   slice_a=array.array('B',[ord(i) for i in a])#a[:]
   slice_b=array.array('B',[ord(i) for i in b])#b[:];
  except:
   slice_a=array.array('B',[i for i in a])#a[:]
   slice_b=array.array('B',[i for i in b])#b[:];

  prefix_a=KeyPrefix()
  prefix_b=KeyPrefix()
  ok_a = prefix_a.Decode(slice_a)
  ok_b = prefix_b.Decode(slice_b)
  if not ok_a or not ok_b:
      return(False,0)
  x=  prefix_a.Compare(prefix_b)
  if x!=0: return (True,x)
  ctp=prefix_a.ctype()
  #print(ctp)
  if ctp== KeyPrefix.GLOBAL_METADATA: 
     (ok, type_byte_a)=DecodeByte(slice_a)
     if not ok: return (False,0)
     (ok, type_byte_b)=DecodeByte(slice_b)
     if not ok: return (False,0)
     x=cmp(type_byte_a,type_byte_b)
     if x!=0: return (True,x)
     if type_byte_a < kMaxSimpleGlobalMetaDataTypeByte:
        return (True,0)
     #print(type_byte_a)   
     if type_byte_a == kDatabaseFreeListTypeByte:
        (ok,var_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,var_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        return (True,cmp(var_a,var_b))
     elif type_byte_a == kDatabaseNameTypeByte:
        (ok,origin_a)=DecodeStringWithLength(slice_a)
        if not ok: return (False,0)
        (ok,origin_b)=DecodeStringWithLength(slice_b)
        if not ok: return (False,0)
        x=cmp(origin_a,origin_b)
        if x!=0:return (True,x)
        (ok,dname_a)=DecodeStringWithLength(slice_a)
        if not ok: return (False,0)
        (ok,dname_b)=DecodeStringWithLength(slice_b)
        if not ok: return (False,0)
        return (True,cmp(dname_a,dname_b))
  elif ctp==KeyPrefix.DATABASE_METADATA:
     (ok, type_byte_a)=DecodeByte(slice_a)
     if not ok: return (False,0)
     (ok, type_byte_b)=DecodeByte(slice_b)
     if not ok: return (False,0)
     x=cmp(type_byte_a,type_byte_b)
     if x!=0: return (True,x)
     if (type_byte_a < 6):
        return (True,0)
     if type_byte_a == kObjectStoreMetaDataTypeByte:   
        (ok,var_a)=DecodeByte(slice_a)
        if not ok: return (False,0)
        (ok,var_b)=DecodeByte(slice_b)
        if not ok: return (False,0)
        return (True,cmp(var_a,var_b))
     elif  type_byte_a == kIndexMetaDataTypeByte:
        (ok,oid_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,oid_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        x = cmp(oid_a,oid_b)
        if x!=0: return (True,x)
        (ok,iid_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,iid_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        x = cmp(iid_a,iid_b)
        if x!=0: return (True,x)
        (ok,var_a)=DecodeByte(slice_a)
        if not ok: return (False,0)
        (ok,var_b)=DecodeByte(slice_b)
        if not ok: return (False,0)
        return (True,cmp(var_a,var_b)  )
     elif type_byte_a == kObjectStoreFreeListTypeByte:
        (ok,var_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,var_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        return (True,cmp(var_a,var_b))   
     elif type_byte_a == kIndexFreeListTypeByte:
        (ok,oid_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,oid_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        x = cmp(oid_a,oid_b)
        if x!=0: return (True,x)
        (ok,iid_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,iid_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        return (True, cmp(iid_a,iid_b))
     elif type_byte_a == kObjectStoreNamesTypeByte:
        (ok,dname_a)=DecodeStringWithLength(slice_a)
        if not ok: return (False,0)
        (ok,dname_b)=DecodeStringWithLength(slice_b)
        if not ok: return (False,0)
        return (True,cmp(dname_a,dname_b))        
     elif type_byte_a == kIndexNamesKeyTypeByte:
        (ok,oid_a)=DecodeVarInt(slice_a)
        if not ok: return (False,0)
        (ok,oid_b)=DecodeVarInt(slice_b)
        if not ok: return (False,0)
        x = cmp(oid_a,oid_b)
        if x!=0: return (True,x)
        (ok,dname_a)=DecodeStringWithLength(slice_a)
        if not ok: return (False,0)
        (ok,dname_b)=DecodeStringWithLength(slice_b)
        if not ok: return (False,0)
        return (True,cmp(dname_a,dname_b))   
     else: 
         return (False,0)
  elif ctp==KeyPrefix.OBJECT_STORE_DATA:
      if (len(slice_a)==0 or len(slice_b)==0):
        return (True,CompareSizes(len(slice_a), len(slice_b)))
      return CompareSuffix_ObjectStoreDataKey(slice_a, slice_b, False)
  elif ctp==KeyPrefix.EXISTS_ENTRY:    
      if (len(slice_a)==0 or len(slice_b)==0):
        return (True,CompareSizes(len(slice_a), len(slice_b)))
      return CompareSuffix_ExistsEntryKey(slice_a, slice_b, False)
  elif ctp==KeyPrefix.BLOB_ENTRY:    
      if (len(slice_a)==0 or len(slice_b)==0):
        return (True,CompareSizes(len(slice_a), len(slice_b)))
      return CompareSuffix_BlobEntryKey(slice_a, slice_b, False)
  elif ctp==KeyPrefix.INDEX_DATA:    
      if (len(slice_a)==0 or len(slice_b)==0):
        return (True,CompareSizes(len(slice_a), len(slice_b)))
      return CompareSuffix_IndexDataKey(slice_a, slice_b, False)
  else:
      return (False,0)
  print ("Not reached -r1")
  return (False,0)


def Compare(a,b, only_compare_index_keys):
  (ok , result) = Compare_Bool(a, b, only_compare_index_keys)
  if  not ok:
    return 0
  return result

  
def Represent_Key(a):
  try:
   slice_a=array.array('B',[ord(i) for i in a])#a[:]
  except:
   slice_a=array.array('B',[i for i in a])#a[:]

  prefix_a=KeyPrefix()
  ok_a = prefix_a.Decode(slice_a)
  if not ok_a:
      return u"Invalid_Prefix"
  ctp=prefix_a.ctype()
  if ctp== KeyPrefix.GLOBAL_METADATA: 
     (ok, type_byte_a)=DecodeByte(slice_a)
     if not ok: return u"Invalid_Prefix_Type"
     if type_byte_a < kMaxSimpleGlobalMetaDataTypeByte:
        return u"Simple_Metadata_{}".format(type_byte_a)
     if type_byte_a == kDatabaseFreeListTypeByte:
        (ok,var_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_Metadata_FreeList"
        return u"Metadata_FreeList_{}".format(var_a)
     elif type_byte_a == kDatabaseNameTypeByte:
        (ok,origin_a)=DecodeStringWithLength(slice_a)
        if not ok: return "Invalid_Metadata_Name"
        (ok,dname_a)=DecodeStringWithLength(slice_a)
        if not ok: return "Invalid_Metadata_Name"
        return u"Metadata_Name_{}_{}".format(origin_a,dname_a)
  elif ctp==KeyPrefix.DATABASE_METADATA:
     (ok, type_byte_a)=DecodeByte(slice_a)
     if not ok: return u"Invalid_Database_Metadata"
     if (type_byte_a < 6):
        return u"Simple_Database_Metadata_{}".format(type_byte_a)
     if type_byte_a == kObjectStoreMetaDataTypeByte:   
        (ok,var_a)=DecodeByte(slice_a)
        if not ok: return u"Invalid_Metadata_Database_ObjectStore"
        return u"Metadata_ObjectStore_{}".format(var_a)
     elif  type_byte_a == kIndexMetaDataTypeByte:
        (ok,oid_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_Metadata_Index"
        (ok,iid_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_Metadata_Index"
        (ok,var_a)=DecodeByte(slice_a)
        if not ok: return u"Invalid_Metadata_Index"
        return u"Metadata_Index_{}_{}_{}".format(oid_a,iid_a,var_a)
     elif type_byte_a == kObjectStoreFreeListTypeByte:
        (ok,var_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_ObjectstoreFreelistMeta"
        return u"Metadata_ObjectStoreFreeList_{}".format(var_a)
     elif type_byte_a == kIndexFreeListTypeByte:
        (ok,oid_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_Metadata_IndexFreeList"
        (ok,iid_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_Metadata_IndexFreeList"
        return "Metadata_Index_Freelist_{}_{}".format(oid_a,iid_a)
     elif type_byte_a == kObjectStoreNamesTypeByte:
        (ok,dname_a)=DecodeStringWithLength(slice_a)
        if not ok: return u"Invalid_Metadata_DBNames"
        return u"Metadata_DBNames_{}".format(dname_a)      
     elif type_byte_a == kIndexNamesKeyTypeByte:
        (ok,oid_a)=DecodeVarInt(slice_a)
        if not ok: return u"Invalid_Metadata_IndexNames"
        (ok,dname_a)=DecodeStringWithLength(slice_a)
        if not ok: return u"Invalid_Metadata_IndexNames"
        return u"Metadata_IndexNames_{}_{}".format(oid_a,dname_a)
     else: 
         return u"Invalid_Metatype"
  elif ctp==KeyPrefix.OBJECT_STORE_DATA:
      if (len(slice_a)==0):
        return u"Degenerate_Key_{}".format(repr(prefix_a))
      (ok,key)=DecodeIDBKey(slice_a)
      if not ok: return u"Invalid_Object_Store_Key"      
      return u"Object_Store_{}".format(repr(key))
  elif ctp==KeyPrefix.EXISTS_ENTRY:    
      if (len(slice_a)==0):
        return u"Degenerate_Key_{}".format(repr(prefix_a))
      (ok,key)=DecodeIDBKey(slice_a)
      if not ok: return u"Invalid_Exists_Entry_Key"      
      return u"Exists_Entry_{}".format(repr(key))
  elif ctp==KeyPrefix.BLOB_ENTRY:    
      if (len(slice_a)==0 ):
        return u"Degenerate_Key_{}".format(repr(prefix_a))
      (ok,key)=DecodeIDBKey(slice_a)
      if not ok: return u"Invalid_Blob_Entry_Key"      
      return u"Blob_Entry_{}".format(repr(key))
  elif ctp==KeyPrefix.INDEX_DATA:    
      if (len(slice_a)==0):
        return u"Degenerate_Key_{}".format(repr(prefix_a))
      (ok,key)=DecodeIDBKey(slice_a)  
      if not ok: return u"Invalid_Index_Data_Key"
      (ok, sequence_number_a) = DecodeVarInt(slice_a)
      if not ok: return  u"Index_Data_{}".format(repr(key))
      if len(slice_a)==0:
        return u"Index_Data_{}".format(repr(key))
      (ok,key2)=DecodeIDBKey(slice_a) 
      if not ok: u"Index_Data_{}_{}".format(repr(key),sequence_number_a)
      return u"Index_Data_{}_{}_{}".format(repr(key),sequence_number_a,repr(key1))
  else:
      return u"Invalid_Key"
  return u"Not reached -r2"
  
import pprint  
pp = pprint.PrettyPrinter(indent=2)
def Represent_Datakey(a):
    try:
      slice_a=array.array('B',[ord(i) for i in a])#a[:]
    except:
     slice_a=array.array('B',[i for i in a])
    if (len(slice_a)==0):
     return u"Degenerate_Key".format(repr(slice_a))
    (ok, ver) = DecodeVarInt(slice_a)
    des=V8Deserializer(slice_a)
    #print("slicea")
    #print (slice_a.tostring())
    val=des.Deserialize()
    pp.pprint(val)
    return val

def Parse_Datakey(a):
    try:
      slice_a=array.array('B',[ord(i) for i in a])#a[:]
    except:
     slice_a=array.array('B',[i for i in a])
    if (len(slice_a)==0):
     return u"Degenerate_Key".format(repr(slice_a))
    (ok, ver) = DecodeVarInt(slice_a)
    des=V8Deserializer(slice_a)
    val=des.Deserialize()
    return val
    
class SerializationTag:
  # version:uint32_t (if at beginning of data, sets version > 0)
  kVersion = 0xFF
  # ignore
  kPadding = 0
  # refTableSize:uint32_t (previously used for sanity checks; safe to ignore)
  kVerifyObjectCount = ord('?')
  # Oddballs (no data).
  kTheHole = ord('-')
  kUndefined = ord('_')
  kNull = ord('0')
  kTrue = ord('T')
  kFalse = ord('F')
  # Number represented as 32-bit integer, ZigZag-encoded
  # (like sint32 in protobuf)
  kInt32 = ord('I')
  # Number represented as 32-bit unsigned integer, varint-encoded
  #(like uint32 in protobuf)
  kUint32 = ord('U')
  # Number represented as a 64-bit double.
  #Host byte order is used (N.B. this makes the format non-portable).
  kDouble = ord('N')
  # BigInt. Bitfield:uint32_t, then raw digits storage.
  kBigInt = ord('Z')
  #byteLength:uint32_t, then raw data
  kUtf8String = ord('S')
  kOneByteString = ord('"')
  kTwoByteString = ord('c')
  # Reference to a serialized object. objectID:uint32_t
  kObjectReference = ord('^')
  # Beginning of a JS object.
  kBeginJSObject = ord('o')
  # End of a JS object. numProperties:uint32_t
  kEndJSObject = ord('{')
  # Beginning of a sparse JS array. length:uint32_t
  # Elements and properties are written as key/value pairs, like objects.
  kBeginSparseJSArray = ord('a')
  # End of a sparse JS array. numProperties:uint32_t length:uint32_t
  kEndSparseJSArray = ord('@') 
  # Beginning of a dense JS array. length:uint32_t
  # |length| elements, followed by properties as key/value pairs
  kBeginDenseJSArray = ord('A')
  # End of a dense JS array. numProperties:uint32_t length:uint32_t
  kEndDenseJSArray = ord('$')
  # Date. millisSinceEpoch:double
  kDate = ord('D')
  # Boolean object. No data.
  kTrueObject = ord('y')
  kFalseObject = ord('x')
  # Number object. value:double
  kNumberObject = ord('n')
  # BigInt object. Bitfield:uint32_t, then raw digits storage.
  kBigIntObject = ord('z')
  # String object, UTF-8 encoding. byteLength:uint32_t, then raw data.
  kStringObject = ord('s') 
  # Regular expression, UTF-8 encoding. byteLength:uint32_t, raw data,
  # flags:uint32_t.
  kRegExp = ord('R') 
  # Beginning of a JS map.
  kBeginJSMap = ord(';')
  # End of a JS map. length:uint32_t.
  kEndJSMap = ord(':')
  # Beginning of a JS set.
  kBeginJSSet = ord('\'')
  # End of a JS set. length:uint32_t.
  kEndJSSet = ord(',')
  #/ Array buffer. byteLength:uint32_t, then raw data.
  kArrayBuffer = ord('B') 
  # Array buffer (transferred). transferID:uint32_t
  kArrayBufferTransfer = ord('t')
  # View into an array buffer.
  # subtag:ArrayBufferViewTag, byteOffset:uint32_t, byteLength:uint32_t
  # For typed arrays, byteOffset and byteLength must be divisible by the size
  # of the element.
  # Note: kArrayBufferView is special, and should have an ArrayBuffer (or an
  # ObjectReference to one) serialized just before it. This is a quirk arising
  # from the previous stack-based implementation.
  kArrayBufferView = ord('V')
  # Shared array buffer. transferID:uint32_t
  kSharedArrayBuffer = ord('u')
  # Compiled WebAssembly module. encodingType:(one-byte tag).
  # If encodingType == 'y' (raw bytes):
  #  wasmWireByteLength:uint32_t, then raw data
  #  compiledDataLength:uint32_t, then raw data
  kWasmModule = ord('W')
  # A wasm module object transfer. next value is its index.
  kWasmModuleTransfer = ord('w')
  # The delegate is responsible for processing all following data.
  # This "escapes" to whatever wire format the delegate chooses.
  kHostObject = ord('\\')
  # A transferred WebAssembly.Memory object. maximumPages:int32_t, then by
  # SharedArrayBuffer tag and its data.
  kWasmMemoryTransfer = ord('m') 


"""
bool KeyPrefix::IsValidDatabaseId(int64 database_id) {
  return (database_id > 0) && (database_id < KeyPrefix::kMaxDatabaseId);
}

bool KeyPrefix::IsValidObjectStoreId(int64 object_store_id) {
  return (object_store_id > 0) &&
         (object_store_id < KeyPrefix::kMaxObjectStoreId);
}

bool KeyPrefix::IsValidIndexId(int64 index_id) {
  return (index_id >= kMinimumIndexId) && (index_id < KeyPrefix::kMaxIndexId);
}


"""

"""
std::string SchemaVersionKey::Encode() {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kSchemaVersionTypeByte);
  return ret;
}

std::string MaxDatabaseIdKey::Encode() {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kMaxDatabaseIdTypeByte);
  return ret;
}

std::string DataVersionKey::Encode() {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kDataVersionTypeByte);
  return ret;
}

std::string BlobJournalKey::Encode() {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kBlobJournalTypeByte);
  return ret;
}

std::string LiveBlobJournalKey::Encode() {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kLiveBlobJournalTypeByte);
  return ret;
}

DatabaseFreeListKey::DatabaseFreeListKey() : database_id_(-1) {}

bool DatabaseFreeListKey::Decode(StringPiece* slice,
                                 DatabaseFreeListKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(!prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kDatabaseFreeListTypeByte);
  if (!DecodeVarInt(slice, &result->database_id_))
    return false;
  return true;
}

std::string DatabaseFreeListKey::Encode(int64 database_id) {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kDatabaseFreeListTypeByte);
  EncodeVarInt(database_id, &ret);
  return ret;
}

std::string DatabaseFreeListKey::EncodeMaxKey() {
  return Encode(std::numeric_limits<int64>::max());
}

int64 DatabaseFreeListKey::DatabaseId() const {
  DCHECK_GE(database_id_, 0);
  return database_id_;
}

int DatabaseFreeListKey::Compare(const DatabaseFreeListKey& other) const {
  DCHECK_GE(database_id_, 0);
  return CompareInts(database_id_, other.database_id_);
}

bool DatabaseNameKey::Decode(StringPiece* slice, DatabaseNameKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(!prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kDatabaseNameTypeByte);
  if (!DecodeStringWithLength(slice, &result->origin_))
    return false;
  if (!DecodeStringWithLength(slice, &result->database_name_))
    return false;
  return true;
}

std::string DatabaseNameKey::Encode(const std::string& origin_identifier,
                                    const base::string16& database_name) {
  std::string ret = KeyPrefix::EncodeEmpty();
  ret.push_back(kDatabaseNameTypeByte);
  EncodeStringWithLength(base::ASCIIToUTF16(origin_identifier), &ret);
  EncodeStringWithLength(database_name, &ret);
  return ret;
}

std::string DatabaseNameKey::EncodeMinKeyForOrigin(
    const std::string& origin_identifier) {
  return Encode(origin_identifier, base::string16());
}

std::string DatabaseNameKey::EncodeStopKeyForOrigin(
    const std::string& origin_identifier) {
  // just after origin in collation order
  return EncodeMinKeyForOrigin(origin_identifier + '\x01');
}

int DatabaseNameKey::Compare(const DatabaseNameKey& other) {
  if (int x = origin_.compare(other.origin_))
    return x;
  return database_name_.compare(other.database_name_);
}

bool DatabaseMetaDataKey::IsValidBlobKey(int64 blob_key) {
  return blob_key >= kBlobKeyGeneratorInitialNumber;
}

const int64 DatabaseMetaDataKey::kAllBlobsKey = 1;
const int64 DatabaseMetaDataKey::kBlobKeyGeneratorInitialNumber = 2;
const int64 DatabaseMetaDataKey::kInvalidBlobKey = -1;

std::string DatabaseMetaDataKey::Encode(int64 database_id,
                                        MetaDataType meta_data_type) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(meta_data_type);
  return ret;
}

ObjectStoreMetaDataKey::ObjectStoreMetaDataKey()
    : object_store_id_(-1), meta_data_type_(0xFF) {}

bool ObjectStoreMetaDataKey::Decode(StringPiece* slice,
                                    ObjectStoreMetaDataKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kObjectStoreMetaDataTypeByte);
  if (!DecodeVarInt(slice, &result->object_store_id_))
    return false;
  DCHECK(result->object_store_id_);
  if (!DecodeByte(slice, &result->meta_data_type_))
    return false;
  return true;
}

std::string ObjectStoreMetaDataKey::Encode(int64 database_id,
                                           int64 object_store_id,
                                           unsigned char meta_data_type) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(kObjectStoreMetaDataTypeByte);
  EncodeVarInt(object_store_id, &ret);
  ret.push_back(meta_data_type);
  return ret;
}

std::string ObjectStoreMetaDataKey::EncodeMaxKey(int64 database_id) {
  return Encode(database_id,
                std::numeric_limits<int64>::max(),
                kObjectMetaDataTypeMaximum);
}

std::string ObjectStoreMetaDataKey::EncodeMaxKey(int64 database_id,
                                                 int64 object_store_id) {
  return Encode(database_id, object_store_id, kObjectMetaDataTypeMaximum);
}

int64 ObjectStoreMetaDataKey::ObjectStoreId() const {
  DCHECK_GE(object_store_id_, 0);
  return object_store_id_;
}
unsigned char ObjectStoreMetaDataKey::MetaDataType() const {
  return meta_data_type_;
}

int ObjectStoreMetaDataKey::Compare(const ObjectStoreMetaDataKey& other) {
  DCHECK_GE(object_store_id_, 0);
  if (int x = CompareInts(object_store_id_, other.object_store_id_))
    return x;
  return meta_data_type_ - other.meta_data_type_;
}

IndexMetaDataKey::IndexMetaDataKey()
    : object_store_id_(-1), index_id_(-1), meta_data_type_(0) {}

bool IndexMetaDataKey::Decode(StringPiece* slice, IndexMetaDataKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kIndexMetaDataTypeByte);
  if (!DecodeVarInt(slice, &result->object_store_id_))
    return false;
  if (!DecodeVarInt(slice, &result->index_id_))
    return false;
  if (!DecodeByte(slice, &result->meta_data_type_))
    return false;
  return true;
}

std::string IndexMetaDataKey::Encode(int64 database_id,
                                     int64 object_store_id,
                                     int64 index_id,
                                     unsigned char meta_data_type) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(kIndexMetaDataTypeByte);
  EncodeVarInt(object_store_id, &ret);
  EncodeVarInt(index_id, &ret);
  EncodeByte(meta_data_type, &ret);
  return ret;
}

std::string IndexMetaDataKey::EncodeMaxKey(int64 database_id,
                                           int64 object_store_id) {
  return Encode(database_id,
                object_store_id,
                std::numeric_limits<int64>::max(),
                kIndexMetaDataTypeMaximum);
}

std::string IndexMetaDataKey::EncodeMaxKey(int64 database_id,
                                           int64 object_store_id,
                                           int64 index_id) {
  return Encode(
      database_id, object_store_id, index_id, kIndexMetaDataTypeMaximum);
}

int IndexMetaDataKey::Compare(const IndexMetaDataKey& other) {
  DCHECK_GE(object_store_id_, 0);
  DCHECK_GE(index_id_, 0);

  if (int x = CompareInts(object_store_id_, other.object_store_id_))
    return x;
  if (int x = CompareInts(index_id_, other.index_id_))
    return x;
  return meta_data_type_ - other.meta_data_type_;
}

int64 IndexMetaDataKey::IndexId() const {
  DCHECK_GE(index_id_, 0);
  return index_id_;
}

ObjectStoreFreeListKey::ObjectStoreFreeListKey() : object_store_id_(-1) {}

bool ObjectStoreFreeListKey::Decode(StringPiece* slice,
                                    ObjectStoreFreeListKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kObjectStoreFreeListTypeByte);
  if (!DecodeVarInt(slice, &result->object_store_id_))
    return false;
  return true;
}

std::string ObjectStoreFreeListKey::Encode(int64 database_id,
                                           int64 object_store_id) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(kObjectStoreFreeListTypeByte);
  EncodeVarInt(object_store_id, &ret);
  return ret;
}

std::string ObjectStoreFreeListKey::EncodeMaxKey(int64 database_id) {
  return Encode(database_id, std::numeric_limits<int64>::max());
}

int64 ObjectStoreFreeListKey::ObjectStoreId() const {
  DCHECK_GE(object_store_id_, 0);
  return object_store_id_;
}

int ObjectStoreFreeListKey::Compare(const ObjectStoreFreeListKey& other) {
  // TODO(jsbell): It may seem strange that we're not comparing database id's,
  // but that comparison will have been made earlier.
  // We should probably make this more clear, though...
  DCHECK_GE(object_store_id_, 0);
  return CompareInts(object_store_id_, other.object_store_id_);
}

IndexFreeListKey::IndexFreeListKey() : object_store_id_(-1), index_id_(-1) {}

bool IndexFreeListKey::Decode(StringPiece* slice, IndexFreeListKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kIndexFreeListTypeByte);
  if (!DecodeVarInt(slice, &result->object_store_id_))
    return false;
  if (!DecodeVarInt(slice, &result->index_id_))
    return false;
  return true;
}

std::string IndexFreeListKey::Encode(int64 database_id,
                                     int64 object_store_id,
                                     int64 index_id) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(kIndexFreeListTypeByte);
  EncodeVarInt(object_store_id, &ret);
  EncodeVarInt(index_id, &ret);
  return ret;
}

std::string IndexFreeListKey::EncodeMaxKey(int64 database_id,
                                           int64 object_store_id) {
  return Encode(
      database_id, object_store_id, std::numeric_limits<int64>::max());
}

int IndexFreeListKey::Compare(const IndexFreeListKey& other) {
  DCHECK_GE(object_store_id_, 0);
  DCHECK_GE(index_id_, 0);
  if (int x = CompareInts(object_store_id_, other.object_store_id_))
    return x;
  return CompareInts(index_id_, other.index_id_);
}

int64 IndexFreeListKey::ObjectStoreId() const {
  DCHECK_GE(object_store_id_, 0);
  return object_store_id_;
}

int64 IndexFreeListKey::IndexId() const {
  DCHECK_GE(index_id_, 0);
  return index_id_;
}

// TODO(jsbell): We never use this to look up object store ids,
// because a mapping is kept in the IndexedDBDatabase. Can the
// mapping become unreliable?  Can we remove this?
bool ObjectStoreNamesKey::Decode(StringPiece* slice,
                                 ObjectStoreNamesKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kObjectStoreNamesTypeByte);
  if (!DecodeStringWithLength(slice, &result->object_store_name_))
    return false;
  return true;
}

std::string ObjectStoreNamesKey::Encode(
    int64 database_id,
    const base::string16& object_store_name) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(kObjectStoreNamesTypeByte);
  EncodeStringWithLength(object_store_name, &ret);
  return ret;
}

int ObjectStoreNamesKey::Compare(const ObjectStoreNamesKey& other) {
  return object_store_name_.compare(other.object_store_name_);
}

IndexNamesKey::IndexNamesKey() : object_store_id_(-1) {}

// TODO(jsbell): We never use this to look up index ids, because a mapping
// is kept at a higher level.
bool IndexNamesKey::Decode(StringPiece* slice, IndexNamesKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(!prefix.object_store_id_);
  DCHECK(!prefix.index_id_);
  unsigned char type_byte = 0;
  if (!DecodeByte(slice, &type_byte))
    return false;
  DCHECK_EQ(type_byte, kIndexNamesKeyTypeByte);
  if (!DecodeVarInt(slice, &result->object_store_id_))
    return false;
  if (!DecodeStringWithLength(slice, &result->index_name_))
    return false;
  return true;
}

std::string IndexNamesKey::Encode(int64 database_id,
                                  int64 object_store_id,
                                  const base::string16& index_name) {
  KeyPrefix prefix(database_id);
  std::string ret = prefix.Encode();
  ret.push_back(kIndexNamesKeyTypeByte);
  EncodeVarInt(object_store_id, &ret);
  EncodeStringWithLength(index_name, &ret);
  return ret;
}

int IndexNamesKey::Compare(const IndexNamesKey& other) {
  DCHECK_GE(object_store_id_, 0);
  if (int x = CompareInts(object_store_id_, other.object_store_id_))
    return x;
  return index_name_.compare(other.index_name_);
}

ObjectStoreDataKey::ObjectStoreDataKey() {}
ObjectStoreDataKey::~ObjectStoreDataKey() {}

bool ObjectStoreDataKey::Decode(StringPiece* slice,
                                ObjectStoreDataKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(prefix.object_store_id_);
  DCHECK_EQ(prefix.index_id_, kSpecialIndexNumber);
  if (!ExtractEncodedIDBKey(slice, &result->encoded_user_key_))
    return false;
  return true;
}

std::string ObjectStoreDataKey::Encode(int64 database_id,
                                       int64 object_store_id,
                                       const std::string encoded_user_key) {
  KeyPrefix prefix(KeyPrefix::CreateWithSpecialIndex(
      database_id, object_store_id, kSpecialIndexNumber));
  std::string ret = prefix.Encode();
  ret.append(encoded_user_key);

  return ret;
}

std::string ObjectStoreDataKey::Encode(int64 database_id,
                                       int64 object_store_id,
                                       const IndexedDBKey& user_key) {
  std::string encoded_key;
  EncodeIDBKey(user_key, &encoded_key);
  return Encode(database_id, object_store_id, encoded_key);
}

scoped_ptr<IndexedDBKey> ObjectStoreDataKey::user_key() const {
  scoped_ptr<IndexedDBKey> key;
  StringPiece slice(encoded_user_key_);
  if (!DecodeIDBKey(&slice, &key)) {
    // TODO(jsbell): Return error.
  }
  return key.Pass();
}

const int64 ObjectStoreDataKey::kSpecialIndexNumber = kObjectStoreDataIndexId;

ExistsEntryKey::ExistsEntryKey() {}
ExistsEntryKey::~ExistsEntryKey() {}

bool ExistsEntryKey::Decode(StringPiece* slice, ExistsEntryKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(prefix.object_store_id_);
  DCHECK_EQ(prefix.index_id_, kSpecialIndexNumber);
  if (!ExtractEncodedIDBKey(slice, &result->encoded_user_key_))
    return false;
  return true;
}

std::string ExistsEntryKey::Encode(int64 database_id,
                                   int64 object_store_id,
                                   const std::string& encoded_key) {
  KeyPrefix prefix(KeyPrefix::CreateWithSpecialIndex(
      database_id, object_store_id, kSpecialIndexNumber));
  std::string ret = prefix.Encode();
  ret.append(encoded_key);
  return ret;
}

std::string ExistsEntryKey::Encode(int64 database_id,
                                   int64 object_store_id,
                                   const IndexedDBKey& user_key) {
  std::string encoded_key;
  EncodeIDBKey(user_key, &encoded_key);
  return Encode(database_id, object_store_id, encoded_key);
}

scoped_ptr<IndexedDBKey> ExistsEntryKey::user_key() const {
  scoped_ptr<IndexedDBKey> key;
  StringPiece slice(encoded_user_key_);
  if (!DecodeIDBKey(&slice, &key)) {
    // TODO(jsbell): Return error.
  }
  return key.Pass();
}

const int64 ExistsEntryKey::kSpecialIndexNumber = kExistsEntryIndexId;

bool BlobEntryKey::Decode(StringPiece* slice, BlobEntryKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(prefix.object_store_id_);
  DCHECK_EQ(prefix.index_id_, kSpecialIndexNumber);

  if (!ExtractEncodedIDBKey(slice, &result->encoded_user_key_))
    return false;
  result->database_id_ = prefix.database_id_;
  result->object_store_id_ = prefix.object_store_id_;

  return true;
}

bool BlobEntryKey::FromObjectStoreDataKey(StringPiece* slice,
                                          BlobEntryKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(prefix.object_store_id_);
  DCHECK_EQ(prefix.index_id_, ObjectStoreDataKey::kSpecialIndexNumber);

  if (!ExtractEncodedIDBKey(slice, &result->encoded_user_key_))
    return false;
  result->database_id_ = prefix.database_id_;
  result->object_store_id_ = prefix.object_store_id_;
  return true;
}

std::string BlobEntryKey::ReencodeToObjectStoreDataKey(StringPiece* slice) {
  // TODO(ericu): We could be more efficient here, since the suffix is the same.
  BlobEntryKey key;
  if (!Decode(slice, &key))
    return std::string();

  return ObjectStoreDataKey::Encode(
      key.database_id_, key.object_store_id_, key.encoded_user_key_);
}

std::string BlobEntryKey::EncodeMinKeyForObjectStore(int64 database_id,
                                                     int64 object_store_id) {
  // Our implied encoded_user_key_ here is empty, the lowest possible key.
  return Encode(database_id, object_store_id, std::string());
}

std::string BlobEntryKey::EncodeStopKeyForObjectStore(int64 database_id,
                                                      int64 object_store_id) {
  DCHECK(KeyPrefix::ValidIds(database_id, object_store_id));
  KeyPrefix prefix(KeyPrefix::CreateWithSpecialIndex(
      database_id, object_store_id, kSpecialIndexNumber + 1));
  return prefix.Encode();
}

std::string BlobEntryKey::Encode() const {
  DCHECK(!encoded_user_key_.empty());
  return Encode(database_id_, object_store_id_, encoded_user_key_);
}

std::string BlobEntryKey::Encode(int64 database_id,
                                 int64 object_store_id,
                                 const IndexedDBKey& user_key) {
  std::string encoded_key;
  EncodeIDBKey(user_key, &encoded_key);
  return Encode(database_id, object_store_id, encoded_key);
}

std::string BlobEntryKey::Encode(int64 database_id,
                                 int64 object_store_id,
                                 const std::string& encoded_user_key) {
  DCHECK(KeyPrefix::ValidIds(database_id, object_store_id));
  KeyPrefix prefix(KeyPrefix::CreateWithSpecialIndex(
      database_id, object_store_id, kSpecialIndexNumber));
  return prefix.Encode() + encoded_user_key;
}

const int64 BlobEntryKey::kSpecialIndexNumber = kBlobEntryIndexId;

IndexDataKey::IndexDataKey()
    : database_id_(-1),
      object_store_id_(-1),
      index_id_(-1),
      sequence_number_(-1) {}

IndexDataKey::~IndexDataKey() {}

bool IndexDataKey::Decode(StringPiece* slice, IndexDataKey* result) {
  KeyPrefix prefix;
  if (!KeyPrefix::Decode(slice, &prefix))
    return false;
  DCHECK(prefix.database_id_);
  DCHECK(prefix.object_store_id_);
  DCHECK_GE(prefix.index_id_, kMinimumIndexId);
  result->database_id_ = prefix.database_id_;
  result->object_store_id_ = prefix.object_store_id_;
  result->index_id_ = prefix.index_id_;
  result->sequence_number_ = -1;
  result->encoded_primary_key_ = MinIDBKey();

  if (!ExtractEncodedIDBKey(slice, &result->encoded_user_key_))
    return false;

  // [optional] sequence number
  if (slice->empty())
    return true;
  if (!DecodeVarInt(slice, &result->sequence_number_))
    return false;

  // [optional] primary key
  if (slice->empty())
    return true;
  if (!ExtractEncodedIDBKey(slice, &result->encoded_primary_key_))
    return false;
  return true;
}

std::string IndexDataKey::Encode(int64 database_id,
                                 int64 object_store_id,
                                 int64 index_id,
                                 const std::string& encoded_user_key,
                                 const std::string& encoded_primary_key,
                                 int64 sequence_number) {
  KeyPrefix prefix(database_id, object_store_id, index_id);
  std::string ret = prefix.Encode();
  ret.append(encoded_user_key);
  EncodeVarInt(sequence_number, &ret);
  ret.append(encoded_primary_key);
  return ret;
}

std::string IndexDataKey::Encode(int64 database_id,
                                 int64 object_store_id,
                                 int64 index_id,
                                 const IndexedDBKey& user_key) {
  std::string encoded_key;
  EncodeIDBKey(user_key, &encoded_key);
  return Encode(
      database_id, object_store_id, index_id, encoded_key, MinIDBKey(), 0);
}

std::string IndexDataKey::Encode(int64 database_id,
                                 int64 object_store_id,
                                 int64 index_id,
                                 const IndexedDBKey& user_key,
                                 const IndexedDBKey& user_primary_key) {
  std::string encoded_key;
  EncodeIDBKey(user_key, &encoded_key);
  std::string encoded_primary_key;
  EncodeIDBKey(user_primary_key, &encoded_primary_key);
  return Encode(database_id,
                object_store_id,
                index_id,
                encoded_key,
                encoded_primary_key,
                0);
}

std::string IndexDataKey::EncodeMinKey(int64 database_id,
                                       int64 object_store_id,
                                       int64 index_id) {
  return Encode(
      database_id, object_store_id, index_id, MinIDBKey(), MinIDBKey(), 0);
}

std::string IndexDataKey::EncodeMaxKey(int64 database_id,
                                       int64 object_store_id,
                                       int64 index_id) {
  return Encode(database_id,
                object_store_id,
                index_id,
                MaxIDBKey(),
                MaxIDBKey(),
                std::numeric_limits<int64>::max());
}

int64 IndexDataKey::DatabaseId() const {
  DCHECK_GE(database_id_, 0);
  return database_id_;
}




int64 IndexDataKey::ObjectStoreId() const {
  DCHECK_GE(object_store_id_, 0);
  return object_store_id_;
}

int64 IndexDataKey::IndexId() const {
  DCHECK_GE(index_id_, 0);
  return index_id_;
}

scoped_ptr<IndexedDBKey> IndexDataKey::user_key() const {
  scoped_ptr<IndexedDBKey> key;
  StringPiece slice(encoded_user_key_);
  if (!DecodeIDBKey(&slice, &key)) {
    // TODO(jsbell): Return error.
  }
  return key.Pass();
}

scoped_ptr<IndexedDBKey> IndexDataKey::primary_key() const {
  scoped_ptr<IndexedDBKey> key;
  StringPiece slice(encoded_primary_key_);
  if (!DecodeIDBKey(&slice, &key)) {
    // TODO(jsbell): Return error.
  }
  return key.Pass();
}

int IndexedDBBackingStore::Comparator::Compare(const StringPiece& a,
                                               const StringPiece& b) const {
  return content::Compare(a, b, false /*index_keys*/);
}

const char* IndexedDBBackingStore::Comparator::Name() const {
  return "idb_cmp1";
}
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "src/value-serializer.h"

#include <type_traits>

#include "include/v8-value-serializer-version.h"
#include "src/api.h"
#include "src/base/logging.h"
#include "src/conversions.h"
#include "src/flags.h"
#include "src/handles-inl.h"
#include "src/heap/factory.h"
#include "src/isolate.h"
#include "src/objects-inl.h"
#include "src/objects/js-collection-inl.h"
#include "src/objects/js-regexp-inl.h"
#include "src/objects/ordered-hash-table-inl.h"
#include "src/snapshot/code-serializer.h"
#include "src/transitions.h"
#include "src/wasm/wasm-engine.h"
#include "src/wasm/wasm-objects-inl.h"
#include "src/wasm/wasm-result.h"
#include "src/wasm/wasm-serialization.h"

"""

# Version 9: (imported from Blink)
# Version 10: one-byte (Latin-1) strings
# Version 11: properly separate undefined from the hole in arrays
# Version 12: regexp and string objects share normal string encoding
# Version 13: host objects have an explicit tag (rather than handling all
#             unknown tags)
#
# WARNING: Increasing this value is a change which cannot safely be rolled
# back without breaking compatibility with data stored on disk. It is
# strongly recommended that you do not make such changes near a release
# milestone branch point.
kLatestVersion = 13

KB=(1<<10)
kPretenureThreshold = 100 * KB


def BytesNeededForVarint(vint):
    if vint<0: return -1
    result=1
    vint=(vint>>7)
    while (vint>0):
        result=result+1
        vint=(vint>>7)
        
class ArrayBufferViewTag:
  kInt8Array = ord('b')
  kUint8Array = ord('B')
  kUint8ClampedArray = ord('C')
  kInt16Array = ord('w')
  kUint16Array = ord('W')
  kInt32Array = ord('d')
  kUint32Array = ord('D')
  kFloat32Array = ord('f')
  kFloat64Array = ord('F')
  kBigInt64Array = ord('q')
  kBigUint64Array = ord('Q')
  kDataView = ord('?')

kMessagePortTag = ord('M')
kBlobTag = ord('b')  # uuid:WebCoreString, type:WebCoreString, size:uint64_t ->Blob (ref)
kBlobIndexTag = ord('i')      # index:int32_t -> Blob (ref)
kFileTag = ord('f')           # file:RawFile -> File (ref)
kFileIndexTag = ord('e')      # index:int32_t -> File (ref)
kDOMFileSystemTag = ord('d')  # type:int32_t, name:WebCoreString,
                              # uuid:WebCoreString -> FileSystem (ref)
kFileListTag =ord('l')  # length:uint32_t, files:RawFile[length] -> FileList (ref)
kFileListIndexTag =ord('L')  # length:uint32_t, files:int32_t[length] -> FileList (ref)
kImageDataTag = ord('#')    # tags terminated by ImageSerializationTag::kEnd (see
                        # SerializedColorParams.h), width:uint32_t,
                        # height:uint32_t, pixelDataLength:uint32_t,
                        # data:byte[pixelDataLength]
                        # -> ImageData (ref)
kImageBitmapTag = ord('g')  # tags terminated by ImageSerializationTag::kEnd (see
                          # SerializedColorParams.h), width:uint32_t,
                          # height:uint32_t, pixelDataLength:uint32_t,
                          # data:byte[pixelDataLength]
                          # -> ImageBitmap (ref)
kImageBitmapTransferTag =      ord('G')  # index:uint32_t -> ImageBitmap. For ImageBitmap transfer
kOffscreenCanvasTransferTag = ord('H')  # index, width, height, id:uint32_t ->
                                      # OffscreenCanvas. For OffscreenCanvas
                                      # transfer
kDOMPointTag = ord('Q')                 # x:Double, y:Double, z:Double, w:Double
kDOMPointReadOnlyTag = ord('W')         # x:Double, y:Double, z:Double, w:Double
kDOMRectTag =ord( 'E')          # x:Double, y:Double, width:Double, height:Double
kDOMRectReadOnlyTag = ord('R')  # x:Double, y:Double, width:Double, height:Double
kDOMQuadTag = ord('T')          # p1:Double, p2:Double, p3:Double, p4:Double
kDOMMatrixTag = ord('Y')        # m11..m44: 16 Double
kDOMMatrixReadOnlyTag = ord('U')    # m11..m44: 16 Double
kDOMMatrix2DTag = ord('I')         # a..f: 6 Double
kDOMMatrix2DReadOnlyTag = ord('O')  # a..f: 6 Double
kCryptoKeyTag = ord('K')            # subtag:byte, props, usages:uint32_t,
                        # keyDataLength:uint32_t, keyData:byte[keyDataLength]
  #                 If subtag=AesKeyTag:
  #                     props = keyLengthBytes:uint32_t, algorithmId:uint32_t
  #                 If subtag=HmacKeyTag:
  #                     props = keyLengthBytes:uint32_t, hashId:uint32_t
  #                 If subtag=RsaHashedKeyTag:
  #                     props = algorithmId:uint32_t, type:uint32_t,
  #                     modulusLengthBits:uint32_t,
  #                     publicExponentLength:uint32_t,
  #                     publicExponent:byte[publicExponentLength],
  #                     hashId:uint32_t
  #                 If subtag=EcKeyTag:
  #                     props = algorithmId:uint32_t, type:uint32_t,
  #                     namedCurve:uint32_t
kRTCCertificateTag = ord('k')  # length:uint32_t, pemPrivateKey:WebCoreString,
                             # pemCertificate:WebCoreString
kVersionTag = 0xFF  # version:uint32_t -> Uses this as the file version.
  
try:
 basestring
except:        
  basestring=str  

  
try:
 unicode
except:        
  unicode=str  

import datetime  
def dateFromFloat(l):
    #sec=(serial - 25569) * 86400.0
    dt=datetime.datetime.utcfromtimestamp(sec)
    return dt
class WasmEncodingTag:
  kRawBytes = ord('y')
class GenericObject(object):
    def __init__(self):
        self.cid=-1
        self.idn=-1
        self.isSmi=False
        self.isString=False
        self.isBool=False
        self.isNumber=False
        self.isBigInt=False
        self.isJSReceiver=False
        self.isRegExp=False
        self.regexp_flags=0
        self.instance_type="ODDBALL_TYPE"
        self.value=0
        self.embedder=False
        self.string_type="ONE_BYTE"
    def __repr__(self):
        if self.instance_type=="ODDBALL_TYPE" :
            return self.value.__repr__()
        elif self.instance_type=="HEAP_NUMBER_TYPE":  
            return str(self.value)
        elif  self.instance_type=="MUTABLE_HEAP_NUMBER_TYPE":  
            return str(self.value)
        elif  self.instance_type=="BIGINT_TYPE":  
            return "BigInt_"+repr(self.value.tostring())
        elif  self.instance_type=="JS_TYPED_ARRAY_TYPE" or self.instance_type=="JS_DATA_VIEW_TYPE":  
            return "TArray:"+self.value.__repr__()
        elif self.instance_type=="JS_ARRAY_TYPE":
            return str(self.value) # should be dictionary? 
        elif  self.instance_type=="JS_OBJECT_TYPE" or self.instance_type=="JS_API_OBJECT_TYPE":
            return self.value.__repr__()    
        elif self.instance_type=="JS_SPECIAL_API_OBJECT_TYPE":
            return  self.value.__repr__() 
        elif self.instance_type=="JS_Date_TYPE" :
            return unicode(dateFromFloat(self.value))
        elif self.instance_type=="JS_VALUE_TYPE" :
            return unicode(self.value)
        elif self.instance_type=="JS_REGEXP_TYPE":
            return "RegExp_"+unicode(self.regexp_flags)+"_"+unicode(self.value)
        elif self.instance_type=="JS_MAP_TYPE":
            return unicode(self.value)
        elif self.instance_type=="JS_SET_TYPE":
            return unicode(self.value)
        elif self.instance_type=="JS_ARRAY_BUFFER_TYPE":
            return self.value.__repr__()
        elif self.instance_type=="WASM_MODULE_TYPE":
            return self.value.__repr__()
        elif self.instance_type=="WASM_MEMORY_TYPE":
            return self.value.__repr__()
        return "GenericObject_Unknown_"+self.instance_type+"__"+unicode(self.value)
        
                       
class JSObject(GenericObject):
    def __init__(self):
        GenericObject.__init__(self)
        self.instance_type="JS_OBJECT_TYPE"
        self.value={}
        #self.propmap={}
    def __repr__(self):
        return "JSObject_"+str(self.value)
    #    dct= self.elemmap.copy()    
        #dct.update(self.propmap) 
    #    return "JSObject_"+str(dct)
    
    
class JSArray(GenericObject):
    def __init__(self):
        GenericObject.__init__(self)
        self.instance_type="JS_ARRAY_TYPE"
        self.value={}
    def __repr__(self):
        return "JSArray_"+str(self.value)
                    
class JSArrayBuffer(GenericObject):
    def __init__(self,narr=None):
     GenericObject.__init__(self)
     self.instance_type="JS_ARRAY_BUFFER_TYPE"
     self.id=100
     self.isShared=False
     self.isTransfer=False
     self.transfer_entry=0
     if narr is None:
      self.value=[]
     else:
       self.value=narr[:]   
     self.isTyped=True
     self.typeTag=ArrayBufferViewTag.kInt8Array
     self.offset=0
     self.blen=0   
    def __repr__(self):
        if self.blen>0:
            return "ArrayBuffer_"+str(self.value[self.offset:self.offset+blen])
        else:
            return "ArrayBuffer_"+str(self.value)
                 
class Oddball(GenericObject):
   def __init__(self):
       GenericObject.__init__(self)
       self.instance_type="ODDBALL_TYPE"
       self.tag=SerializationTag.kUndefined
   def __repr__(self):
       if self.tag==SerializationTag.kTheHole:
           return "Odd_Hole"
       elif self.tag==SerializationTag.kUndefined:
           return "Odd_Undefined"
       elif self.tag==SerializationTag.kNull:
           return "Odd_Null"
       elif self.tag==SerializationTag.kTrue:
           return "Odd_True"
       elif self.tag==SerializationTag.kFalse:
           return "Odd_False"
       return "Odd_nt_{}".format(self.tag)
       
class WasmModule(GenericObject):
     def __init__(self):
         GenericObject.__init__(self)
         self.instance_type="WASM_MODULE_TYPE"
         self.wire_bytes=[]
         self.sern=[]
         self.maxpages=1  
         self.abuf=JSArrayBuffer()
         self.abuf.isJSReceiver=True
         self.abuf.instance_type="JS_TYPED_ARRAY_TYPE"
         #self.abuf.value=JSArrayBuffer()
     def __repr__(self):
         return "Wasm_{}_{}_{}".format(self.wire_bytes,self.sern,self.abuf.value)
         
             
class ValueSerializer(object):
    def __init__(self,arr=None,delegate=None):
        if arr is None:
            arr=array.array('B',[])
        self.buf=arr
        self.treat_array_buffer_views_as_host_objects=True
        self.arr_trans_map={}
        self.next_id=1
        self.id_map={}
        self.delegate=delegate
        
    def WriteHeader(self):
        self.WriteTag(SerializationTag.kVersion)
        self.WriteVarint(kLatestVersion)
        return True
    def SetTreatArrayBufferViewsAsHostObjects(self,mode):
        self.treat_array_buffer_views_as_host_objects= mode

    def WriteTag(self,tag):
        #it is only one byte... for now?
        self.buf.append(tag)
        return True
    def WriteVarint(self,value):
        value=int(value)
        if value<0:
            print("Varint less than zero")
            return
        while True:
            self.buf.append((value&0x7f)|0x80)
            value=(value>>7)    
            if value==0:break
        self.arr[-1]=(self.arr[-1] &0x7f)
        return True
    def WriteZigZag(self,value):
        if value<0:
            self.WriteVarint(abs(value)*2-1)
        else:
            self.WriteVarint(value*2)
        return True    
    def WriteDouble(self,value):
        packed = struct.pack('d', value)
        for u in packed:
         try:
          self.buf.append(ord(u))   
         except:
          self.buf.append(u)       
        return True  
    def  WriteOneByteString(self,chars):
        self.WriteVarint(len(chars))
        for u in chars:
         try:
          self.buf.append(ord(u))   
         except:
          self.buf.append(u)      
        return True  
    def  WriteTwoByteString(self,chars):
      try:
        rev= chars.encode("utf-16") 
      except:
        rev=chars
      self.WriteVarint(len(rev))  
      for u in rev:
         try:
          self.buf.append(ord(u))   
         except:
          self.buf.append(u)  
      return True          
    def WriteBigIntContents(self, big): #bigint is just a byte array for now...
        self.WriteVarint(len(big)*8)
        for u in big:
            self.buf.append(u)
        return True    
    def WriteRawBytes(self,src,lng):
        if lng>len(src): lng=len(src)
        for a in src: self.buf.append(a)
    def WriteUint32(self,value):
        return self.WriteVarint(value)
    def WriteUint64(self,value):
        return self.WriteVarint(value)
    def ReleaseBuffer(self):
        return array.array('B',self.buf)
    def Release(self):
        ret=(array.array('B',self.buf),len(self.buf))
        self.buf=array.array('B',[])
        return ret

    def TransferArrayBuffer(self,transfer_id, buff):
        self.arr_trans_map[transfer_id]=buff
    def WriteObject(self,obj):
        if obj.isSmi:
            self.WriteSmi(obj.value)
            return True
        if obj.instance_type=="ODDBALL_TYPE":
            self.WriteOddball(obj)
            return True
        elif  obj.instance_type=="HEAP_NUMBER_TYPE":  
            self.WriteHeapNumber(obj.value)
            return True
        elif  obj.instance_type=="MUTABLE_HEAP_NUMBER_TYPE":  
            self.WriteMutableHeapNumber(obj.value)
            return True
        elif  obj.instance_type=="BIGINT_TYPE":  
            self.WriteBigInt(obj.value)
            return True
        elif  obj.instance_type=="JS_TYPED_ARRAY_TYPE" or obj.instance_type=="JS_DATA_VIEW_TYPE":  
            #more stuff here?
            #Despite being JSReceivers, these have their wrapped buffer serialized
            # first. That makes this logic a little quirky, because it needs to happen before we assign object IDs.
            # TODO(jbroman): It may be possible to avoid materializing a typed array's buffer here.
            #Handle<JSArrayBufferView> view = Handle<JSArrayBufferView>::cast(object);
            #if (!id_map_.Find(view) && !treat_array_buffer_views_as_host_objects_) {
            # Handle<JSArrayBuffer> buffer(
            #view->IsJSTypedArray()
            #    ? Handle<JSTypedArray>::cast(view)->GetBuffer()
            #    : handle(JSArrayBuffer::cast(view->buffer()), isolate_));
            #if (!WriteJSReceiver(buffer).FromMaybe(false)) return Nothing<bool>();
            return self.WriteJSReceiver(obj.value)
        else:
            if obj.isString: 
                self.WriteString(obj.value)    
                return True
            elif obj.isJSReceiver:
               return self.WriteJSReceiver(obj)
            else:
                 print("Ivalid JS object")     
                 return False
    def WriteOddball(self,value):
        self.WriteTag(value.tag)
        return True
    def WriteSmi(self,smi): #smi is just integer
        self.WriteTag(SerializationTag.kInt32)
        self.WriteZigZag(smi)
        return True
    def WriteHeapNumber(self,num):
        self.WriteTag(SerializationTag.kDouble)    
        self.WriteDouble(float(num))
        return True
    def WriteMutableHeapNumber(self,num):
        self.WriteTag(SerializationTag.kDouble)    
        self.WriteDouble(float(num))
        return True
    def WriteBigInt(self, big):
        self.WriteTag(SerializationTag.kBigInt)    
        self.WriteBigIntContents(big)
        return True
    def WriteString (self,stg):
        if stg.string_type=="ONE_BYTE":
            self.WriteTag(SerializationTag.kOneByteString) 
            return self.WriteOneByteString(stg.value)
        elif stg.string_type=="TWO_BYTE":
            byte_length = len(stg.value) * 2;
            if ((len(self.buf) + 1 + self.BytesNeededForVarint(byte_length)) & 1):
              self.WriteTag(SerializationTag.kPadding)
            self.WriteTag(SerializationTag.kTwoByteString)  #might need algnment?
            return self.WriteTwoByteString(stg.value)
        else:
            print("Unreachable string wrap")     
            return False
    def WriteJSReceiver(self,obj):
        if obj.cid!=-1 and obj.cid in self.id_map:
            self.WriteTag(SerializationTag.kObjectReference)
            self.WriteVarint(obj.cid-1)
            return True
        obj.cid= self.next_id
        self.next_id=self.next_id+1
        self.id_map[obj.cid]=obj
        it=obj.instance_type
        if it=="JS_ARRAY_TYPE":
            return self.WriteJSArray(obj.value)
        elif  it=="JS_OBJECT_TYPE" or it=="JS_API_OBJECT_TYPE":
            if obj.value.embedder:
                return self.WriteHostObject(obj.value)
            else:
                return self.WriteJSObject(obj.value)    
        elif it=="JS_SPECIAL_API_OBJECT_TYPE":
            return  self.WriteHostObject(obj.value)
        elif it=="JS_Date_TYPE" :
            return self.WriteJSDate(obj.value)
        elif it=="JS_VALUE_TYPE" :
            return self.WriteJSValue(obj.value)
        elif it=="JS_REGEXP_TYPE":
            self.WriteJSRegExp(obj.value)
            return True
        elif it=="JS_MAP_TYPE":
            return self.WriteJSMap(obj.value)
        elif it=="JS_SET_TYPE":
            return self.WriteJSSet(obj.value)
        elif it=="JS_ARRAY_BUFFER_TYPE":
            return self.WriteJSArrayBuffer(obj)
        elif  it=="JS_TYPED_ARRAY_TYPE" or it=="JS_DATA_VIEW_TYPE":
            return  self.WriteJSArrayBufferView(obj)
        elif it=="WASM_MODULE_TYPE":
             return self.WriteWasmModule(obj)
        elif it=="WASM_MEMORY_TYPE":
            return self.WriteWasmMemory(obj)
        return False
    def WriteJSObject(self,obj):
        #if len(obj.elemmap)!=0: 
        #    return self.WriteJSObjectSlow(obj)
        self.WriteTag(SerializationTag.kBeginJSObject)
        properties_written = 0
        for key in obj:
            val=obj[key]
            self.WriteString(key)
            self.WriteObject(value)
            properties_written =properties_written+1
        self.WriteTag(SerializationTag.kEndJSObject)   
        self.WriteVarint(properties_written)
        return True
#    def  WriteJSObjectSlow(self,obj):
#       self.WriteTag(SerializationTag.kBeginJSObject) 
#       keys=list(obj.elemmap.keys())
#       keys.extend(obj.propmap.keys())
#       (ret, nump)=self.WriteJSObjectPropertiesSlow(obj,keys)
#       if not ret :return False
#       self.WriteTag(SerializationTag.kEndJSObject)   
#       self.WriteVarint(nump)     
#       return True
       
    def WriteJSArray(self,arr): #js arrays are dicts? hmm. 
        length=len(arr)
        # i don't care about serialization that much...
        self.WriteTag(SerializationTag.kBeginSparseJSArray)
        self.WriteVarint(length)
        prop_wrt=0
        for key in arr:
            if isinstance(key, basestring):
                self.WriteString(key)
            else:
                self.WriteSmi(key)
            self.WriteObject(arr[key])
            prop_wrt=prop_wrt+1
        self.WriteTag(SerializationTag.kEndSparseJSArray)
        self.WriteVarint(prop_wrt)
        self.WriteVarint(length)
        return True
    def   WriteJSDate(self,dt):#date is double
        self.WriteTag(SerializationTag.kDate)
        self.WriteDouble(float(dt))
    def WriteJSValue(self,value): #genericobject?
        if value.isBool and value.value:
            self.WriteTag(SerializationTag.kTrueObject)
            return True
        elif value.isBool and not value.value:    
            self.WriteTag(SerializationTag.kFalseObject)
            return True
        elif value.isNumber:
            self.WriteTag(SerializationTag.kNumberObject)
            self.WriteDouble(value.value)
            return True
        elif value.isBigInt:
            self.WriteTag(SerializationTag.kBigIntObject)
            self.WriteBigIntContents(value.value)
            return True
        elif value.isString:
            self.WriteTag(SerializationTag.kStringObject)
            self.WriteString(value)
            return True
        return False
    def WriteJSRegExp(self, value):
        self.WriteTag(SerializationTag.kRegExp)       
        self.WriteString(value)
        self.WriteVarint(value.regexp_flags)
        return True     
    def WriteJSMap(self, mp):
       self.WriteTag(SerializationTag.kBeginJSMap)
       length=len(mp)
       for key in mp:
           entr=mp[key]
           if isinstance(key, basestring):
              if not  self.WriteString(key):return False
           else:
                if not self.WriteSmi(key) :return False
           if not self.WriteObject(entr): return False
       self.WriteTag(SerializationTag.kEndJSMap)
       self.WriteVarint(length)    
       return True
    def WriteJSSet(self, mp):
       self.WriteTag(SerializationTag.kBeginJSSet)
       length=len(mp)
       for key in mp:
           entr=key
           if not self.WriteObject(entr): return False
       self.WriteTag(SerializationTag.kEndJSSet)
       self.WriteVarint(length)    
       return True
    def WriteJSArrayBuffer(self,jsa):
       if jsa.isShared:
           self.WriteTag(SerializationTag.kSharedArrayBuffer)
           self.WriteVarint(jsa.id)
           return True
       if jsa.isTransfer:
          self.WriteTag(SerializationTag.kArrayBufferTransfer)
          self.WriteVarint(jsa.transfer_entry);
          return True
       length=len(jsa.value)
       self.WriteTag(SerializationTag.kArrayBuffer)
       self.WriteVarint(length)
       self.WriteRawBytes(jsa.value,length)
       return True
    def WriteJSArrayBufferView(self,jsv):
      if self.treat_array_buffer_views_as_host_objects:
          return self.WriteHostObject(jsv)
      self.WriteTag(SerializationTag.kArrayBufferView)    
      tag=ArrayBufferViewTag.kInt8Array
      if jsv.isTyped:
          tag=jsv.typeTag
      else:
          tag= ArrayBufferViewTag.kDataView
      self.WriteVarint(tag)
      self.WriteVarint(jsv.offset)    
      self.WriteVarint(jsv.blen)
    def  WriteWasmModule(self,module):
        encoding_tag = WasmEncodingTag.kRawBytes
        self.WriteTag(SerializationTag.kWasmModule) 
        self.WriteRawBytes([encoding_tag],1)
        self.WriteVarint(len(module.wire_bytes))
        self.WriteRawBytes(module.wire_bytes,len(module.wire_bytes))
        self.WriteVarint(len(module.sern))
        self.WriteRawBytes(module.sern,len(module.sern))
        return True
    def WriteWasmMemory(self,mem):
       self.WriteTag(SerializationTag.kWasmMemoryTransfer)     
       self.WriteZigZag(mem.maxpages) 
       return self.WriteJSReceiver(mem.abuf)
    def WriteHostObject(self,ho):
       self.WriteTag(SerializationTag.kHostObject)
       if self.delegate is None: return False
       return self.delegate.WriteHostObject(ho)
#    def WriteJSObjectPropertiesSlow(self, obj,keys):
#       numw=0
#       for key in keys:
#           if key in obj.elemmap:
#               if not self.WriteString(key): return (False,0)
#               if not self.WriteObject(obj.elemmap[key]): return (False,0)
#               numw=numw+1
#               continue
#           if key in obj.propmap:
#               if not self.WriteString(key): return (False,0)
#               if not self.WriteObject(obj.propmap[key]): return (False,0)
#               numw=numw+1
#               continue               
#       return  (True,numw)

def GetUndefined():
     ret=Oddball()
     ret.tag=SerializationTag.kUndefined
     #tret=GenericObject()
     #tret.instance_type="ODDBALL_TYPE"
     #tret.value=ret
     return ret
def GetNull():
     ret=Oddball()
     ret.tag=SerializationTag.kNull
     #tret=GenericObject()
     #tret.instance_type="ODDBALL_TYPE"
     #tret.value=ret
     return ret
  
def GetTrue():
     ret=Oddball()
     ret.tag=SerializationTag.kTrue
     #tret=GenericObject()
     #tret.instance_type="ODDBALL_TYPE"
     #tret.value=ret
     return ret
def GetFalse():
     ret=Oddball()
     ret.tag=SerializationTag.kFalse
     #tret=GenericObject()
     #tret.instance_type="ODDBALL_TYPE"
     #tret.value=ret
     return ret
def GetInt(vl):
     ret=GenericObject()
     ret.instance_type="JS_VALUE_TYPE"
     ret.value=vl
     ret.isSmi=True
     ret.isNumber=True
     return ret 
def GetUInt(vl):
     ret=GenericObject()
     ret.instance_type="JS_VALUE_TYPE"
     ret.value=vl
     ret.isNumber=True
     return ret     
class ValueDeserializer(object):
      def __init__(self,data,delegate=None):
          self.buf=data
          self.ptr=0
          self.delegate=delegate
          self.array_buffer_transfer_map={}
      def ReadHeader(self):
          vers=None
          if self.ptr<=len(self.buf):
              if self.buf[self.ptr]== SerializationTag.kVersion :
                  self.ReadTag()
                  vers=self.ReadVarint()
                  if vers!=None:
                     if vers> kLatestVersion:
                         print ("Invalid version {}".format(vers))
                         return None
          self.vers=vers  
          self.next_id=1
          self.id_map={}          
          return  vers
      def PeekTag(self):
          kpos=self.ptr
          tag=self.buf[kpos]
          while tag==SerializationTag.kPadding:
              kpos=kpos+1
              if kpos >=len(self.buf): return None
              tag=self.buf[kpos]
          return tag
      def ConsumeTag(self,peeked):
          atag=self.ReadTag()
          if atag!=peeked:
              print("Consume tag error")
            
      def ReadTag(self):
          tag=self.buf[self.ptr]
          while tag==SerializationTag.kPadding:
              self.ptr=self.ptr+1
              if self.ptr >=len(self.buf): return None
              tag=self.buf[self.ptr]
          self.ptr=self.ptr+1  
          printl(6,"Tag: {} {} ".format(tag,chr(tag)))  
          return tag   
      def ReadVarint(self):
          value=0
          shift=0
          hasByte=0
          while True:
              if self.ptr>=len(self.buf): return None
              bt=self.buf[self.ptr]
              value |= ((bt&0x7f)<<shift)
              shift = shift+7 
              self.ptr=self.ptr+1
              hasByte= (bt&0x80)
              if hasByte==0: break
          return value    
      def ReadZigZag(self):
          vr=self.ReadVarint()
          if vr is None: return None
          if (vr%2)>0: return -(1+(vr-1)/2)
          return vr/2
      def ReadDouble(self):
           if len(self.buf)-self.ptr<dleng: return None
           ret=struct.unpack('d',self.buf[self.ptr:self.ptr+dleng])[0]
           self.ptr=self.ptr+dleng
           return ret
      def ReadRawBytes(self,sz):
          if len(self.buf)-self.ptr<sz: return None
          ret=array.array('B',self.buf[self.ptr:self.ptr+sz])
          self.ptr=self.ptr+sz
          return ret
      def ReadUint32(self):
          return self.ReadVarint()
      def ReadUint64(self):
          return self.ReadVarint()
      def TransferArrayBuffer(self,tr_id,abuf):
         self.array_buffer_transfer_map[tr_id]=abuf   
         #self.array_buffer_transfer_map={tr_id:abuf}
      def ReadObject(self):
          res=self.ReadObjectInternal()
          if res is None: return None
          if res.instance_type=="JS_ARRAY_BUFFER_TYPE" and self.PeekTag()==SerializationTag.kArrayBufferView:
              self.ConsumeTag(SerializationTag.kArrayBufferView)
              return self.ReadJSArrayBufferView(res)
          return res
      def ReadObjectInternal(self):
          tag=self.ReadTag()
          #print(tag)
          if tag is None: return None
          if tag ==  SerializationTag.kVerifyObjectCount:   
             cnt=self.ReadVarint()
             if cnt is None: return None
             return self.ReadObject()
          elif tag==SerializationTag.kUndefined:
              return GetUndefined()
          elif tag==SerializationTag.kNull:
              return GetNull()
          elif tag==SerializationTag.kTrue:
              return GetTrue()
          elif tag==SerializationTag.kFalse:
              return GetFalse()
          elif tag==SerializationTag.kInt32:
              num=self.ReadZigZag()
              if num is None: return None
              return GetInt(num)
          elif tag==SerializationTag.kUint32:
              num=self.ReadVarint()
              if num is None: return None
              return GetUInt(num)
          elif tag==SerializationTag.kDouble:
              num=self.ReadDouble()
              if num is None: return None
              return GetUInt(num)
          elif tag==SerializationTag.kBigInt:
              return self.ReadBigInt()
          elif tag==SerializationTag.kUtf8String:
              return self.ReadUtf8String()
          elif tag==SerializationTag.kOneByteString:
              return self.ReadOneByteString()
          elif tag==SerializationTag.kTwoByteString:
              return self.ReadTwoByteString()
          elif tag==SerializationTag.kObjectReference:
              obid=self.ReadVarint()
              if obid==None: return None
              return self.GetObjectWithID(obid)
          elif tag==SerializationTag.kBeginJSObject:
              return self.ReadJSObject()
          elif tag==SerializationTag.kBeginSparseJSArray:
              return self.ReadSparseJSArray()
          elif tag==SerializationTag.kBeginDenseJSArray:
              return self.ReadDenseJSArray()
          elif tag==SerializationTag.kDate:
              return self.RedJSDate()
          elif tag==SerializationTag.kTrueObject or tag==SerializationTag.kFalseObject or tag==SerializationTag.kNumberObject or tag==SerializationTag.kBigIntObject or tag==SerializationTag.kStringObject:
              return self.ReadJSValue(tag)
          elif tag==SerializationTag.kRegExp:
              return self.ReadJSRegExp()
          elif tag==SerializationTag.kBeginJSMap:
              return self.ReadJSMap()
          elif tag==SerializationTag.kBeginJSSet:
              return ReadJSSet()
          elif tag==SerializationTag.kArrayBuffer:
              return self.ReadJSArrayBuffer(False)
          elif tag==SerializationTag.kArrayBufferTransfer:
              return self.ReadTransferredJSArrayBuffer()
          elif tag==SerializationTag.kSharedArrayBuffer:
               return self.ReadJSArrayBuffer(True)
          elif tag==SerializationTag.kWasmModule:
              return self.ReadWasmModule()
          elif tag==SerializationTag.kWasmModuleTransfer:
              return self.ReadWasmModuleTransfer()
          elif tag==SerializationTag.kWasmMemoryTransfer:
              return self.ReadWasmMemory()
          elif tag==SerializationTag.kHostObject:
              return self.ReadHostObject()
          else:
              if self.vers<13: return self.ReadHostObject()
          return None
      def ReadString(self):
          if self.vers<12: return self.ReadUtf8String()
          obj=self.ReadObject()
          if obj is None: return None
          if  not obj.isString: return None
          return obj.value
      def ReadBigInt(self):
          ret=GenericObject()    
          ret.instance_type="BIGINT_TYPE"
          length=self.ReadVarint()
          if length is None: return None
          length=length/8
          ret.value=self.ReadRawBytes(length)
          if ret.value is None: return None
          return ret    
      def ReadUtf8String(self):
          utf8_len=self.ReadVarint()
          if utf8_len is None:return None
          utf8_bytes=self.ReadRawBytes(utf8_len)
          if utf8_bytes is None: return None
          ret=GenericObject() 
          ret.isString=True
          ret.instance_type="JS_VALUE_TYPE"
          ret.value=utf8_bytes.tostring().decode('utf-8')
          ret.byteness=2
          return ret
      def ReadOneByteString(self):
          bytelen=self.ReadVarint()
          if bytelen is None: return None
          raw=self.ReadRawBytes(bytelen)
          if raw is None: return None
          ret=GenericObject() 
          ret.isString=True
          ret.instance_type="JS_VALUE_TYPE"
          ret.value=raw.tostring()
          ret.byteness=1
          return ret
      def ReadTwoByteString(self):
          bytelen=self.ReadVarint()
          if bytelen is None: return None
          if (bytelen %2)>0: return None
          raw=self.ReadRawBytes(bytelen)
          if raw is None: return None
          ret=GenericObject() 
          ret.isString=True
          ret.instance_type="JS_VALUE_TYPE"
          ret.value=raw.tostring().decode('utf-16be')
          ret.byteness=2
          return ret
      def ReadJSObject(self):
          cid=self.next_id
          self.next_id+=1
          ret=JSObject()
          num_properties=self.ReadJSObjectProperties(ret,SerializationTag.kEndJSObject, True)
          if num_properties is None: return None
          act_pros=self.ReadVarint()
          if act_pros is None: return None
          if act_pros != num_properties:
              print ("Property number mismatch")
              return None
          #tret= GenericObject()
          #tret.instance_type="JS_OBJECT_TYPE"
          #tret.value=ret
          self.id_map[cid]=ret    
          return ret    
      def ReadSparseJSArray(self):
          length=self.ReadVarint()
          if length is None: return None
          cid=self.next_id
          self.next_id+=1
          #tret= GenericObject()
          #tret.instance_type="JS_ARRAY_TYPE"
          ret=JSArray()
          ret.cid=cid
          num_properties=self.ReadJSObjectProperties(ret,SerializationTag.kEndSparseJSArray, False)
          if num_properties is None: return None
          exp_prop=self.ReadVarint()
          if exp_prop is None: return None
          exp_len=self.ReadVarint()
          if exp_len is None: return None
          if exp_len!=length:
              print("DictLenMismatch")
              return None
          #tret.value=ret.elemmap
          self.id_map[cid]=ret.value
          return ret
      def ReadDenseJSArray(self):
          length=self.ReadVarint()
          if len(self.buf)-self.ptr<length: return None    
          cid=self.next_id
          self.next_id+=1 
          #tret= GenericObject()
          #tret.instance_type="JS_ARRAY_TYPE" 
          
          ret=JSArray()
          ret.cid=cid
          for i in range(length):
              tag=self.PeekTag()
              if tag is None: return None
              if tag== SerializationTag.kTheHole:
                  self.ConsumeTag(tag)
                  continue
              elem=self.ReadObject()
              if elem is None: return None
              if self.vers<11 and isinstance(elem,Oddball) and elem.tag==SerializationTag.kUndefined:
                  continue
              ret.value[i]=elem
          numpr=self.ReadJSObjectProperties(ret, SerializationTag.kEndDenseJSArray, False)
          if numpr is None: return None
          exp_prop=self.ReadVarint()
          if exp_prop is None: return None
          exp_len=self.ReadVarint()
          if exp_len is None: return None
          if exp_len!=length:
              print("DictLenMismatch: Dense")
              return None      
          self.id_map[cid]=ret.value
          return ret              
      def ReadJSDate(self):
          ret=   GenericObject()
          ret.instance_type="JS_Date_TYPE" 
          cid=self.next_id
          self.next_id+=1 
          ret.value=self.ReadDouble()
          if ret.value is None : return None
          self.id_map[cid]=ret
          return ret
          
      def  ReadJSValue(self,tag):
          cid=self.next_id
          self.next_id+=1 
          tret=GenericObject()
          tret.instance_type="JS_VALUE_TYPE"
          tret.cid=cid
          if tag==SerializationTag.kTrueObject:
              tret.isBool=True
              tret.value=True
          elif  tag==SerializationTag.kFalseObject:
              tret.isBool=True
              tret.value=False
          elif  tag==SerializationTag.kNumberObject:   
              number=self.ReadDouble()
              if number is None:return None
              tret.isNumber=True
              tret.value=number
          elif  tag==SerializationTag.kBigIntObject: 
              tret.isBigInt=True    
              tret.value=self.ReadBigInt()
              if tret.value is None: return None
          elif    tag==SerializationTag.kStringObject:   
              tret.isString=True 
              tret.value=self.ReadString()
              if tret.value is None: return None
          else:
              print("Odd type in serialize : {}".format(tag))
              return None
          if tret.value is None: return None
          self.id_map[cid]=tret
          #print( "Value {} {}",tret,tret.isNumber)
          return tret
      def  ReadJSRegExp(self):
          cid=self.next_id
          self.next_id+=1 
          tret=GenericObject()
          tret.instance_type="JS_REGEXP_TYPE"
          tret.isRegExp=True
          tret.cid=cid
          tret.value=self.ReadString()
          if tret.value is None: return None
          tret.regexp_flags=self.ReadVarint()
          if tret.regexp_flags is None: return None
          self.id_map[cid]=tret
          return tret
      def ReadJSMap(self):
          cid=self.next_id
          self.next_id+=1 
          tret=GenericObject()
          length=0
          tret.instance_type="JS_MAP_TYPE"
          tret.value={}
          while True:
              tg=self.PeekTag()
              if tg is None: return None
              if tg==SerializationTag.kEndJSMap:
                self.ConsumeTag(tg)
                break
              keyv=self.ReadObject()
              if keyv is None: return None
              valuev=self.ReadObject()
              if valuev is None:return None
              tret.value[keyv.value]=valuev
              length+=2
          elen=self.ReadVarint()
          if elen is None:return None
          if elen!= length:
              print( "Unexpected JSMap len")
              return None
          self.id_map[cid]=tret    
          return tret
      def ReadJSSet(self):
          cid=self.next_id
          self.next_id+=1 
          tret=GenericObject()
          tret.cid=cid
          length=0
          tret.instance_type="JS_SET_TYPE"
          tret.value=[]
          while True:
              tg=self.PeekTag()
              if tg is None: return None
              if tg==SerializationTag.kEndJSSet:
                self.ConsumeTag(tg)
                break
              keyv=self.ReadObject()
              if keyv is None: return None
              tret.value.append(valuev)
              length+=1
          elen=self.ReadVarint()
          if elen is None:return None
          if elen!= length:
              print( "Unexpected JSSet len")
              return None
          self.id_map[cid]=tret    
          return tret
       
      def ReadJSArrayBuffer(self, is_shared):
          cid=self.next_id
          self.next_id+=1 
          #ret=JSArrayBuffer()
          if is_shared:
              clone_id=self.ReadVarint()
              if clone_id is None: return None          
              if self.delegate is None: return None
              sharbuf=self.delegate.GetSharedArrayBufferFromId(clone_id)
              if sharbuf is None: return None
              ret=JSArrayBuffer(sharbuf)
              self.id_map[cid]=ret    
              return ret
          blen=self.ReadVarint()
          if blen is None: return None
          ret.value=JSArrayBuffer(self.ReadRawBytes(blen))
          ret.cid=cid
          ret.instance_type="JS_ARRAY_BUFFER_TYPE"
          if ret.value is None: return None
          self.id_map[cid]=ret    
          return ret       
      def  ReadTransferredJSArrayBuffer(self):
          cid=self.next_id
          self.next_id+=1 
          #tret=GenericObject()
          #tret.cid=cid
          #tret.instance_type="JS_ARRAY_BUFFER_TYPE"
          transfer_id=self.ReadVarint()
          if transfer_id is None: return None
          if not transfer_id in self.array_buffer_transfer_map:
              print("Transfer ID {} not found",transfer_id)
              return None
          #tret.value= self.array_buffer_transfer_map[transfer_id]
          #self.id_map[cid]=tret    
          return self.array_buffer_transfer_map[transfer_id]         
      def ReadJSArrayBufferView(self, bfr):
          bfr_blen=len(bfr.value)
          tag=self.ReadVarint()
          if tag is None: return None
          boffs=self.ReadVarint()
          if boffs is None: return None
          blen=self.ReadVarint()
          if blen is None: return None
          cid=self.next_id
          self.next_id+=1 
          ret=JSArrayBuffer(bfr.value[:])
          ret.cid=cid    
          ret.instance_type="JS_TYPED_ARRAY_TYPE"
          if tag== ArrayBufferViewTag.kDataView:
              ret.instance_type="JS_DATA_VIEW_TYPE"
          ret.offset=boffs
          ret.blen=blen
          #no sanity checks...
          self.id_map[cid]=ret    
          return ret          
      def ReadWasmModuleTransfer(self):
          transfer_id=self.ReadVarint()
          if transfer_id is None or self.delegate is None: return None
          modval=self.delegate.GetWasmModuleFromId(transfer_id)
          if modval is None: return None
          cid=self.next_id
          self.next_id+=1 
          tret=GenericObject()
          tret.cid=cid    
          tret.value=modval
          tret.instance_type="WASM_MODULE_TYPE"
          self.id_map[cid]=tret    
          return tret    
      def ReadWasmModule(self):
            etag=self.ReadTag()
            if etag is None or etag!=WasmEncodingTag.kRawBytes  : return None
            wire_bytes_length=self.ReadVarint()
            if wire_bytes_length is None: return None
            cid=self.next_id
            self.next_id+=1 
            tret=GenericObject()
            tret.cid=cid    
            tret.value=WasmModule()
            tret.instance_type="WASM_MODULE_TYPE"
            tret.value.wire_bytes=self.ReadRawBytes(wire_bytes_length)
            if tret.value.wire_bytes is None :return None
            compiled_bytes_length=self.ReadVarint()
            if compiled_bytes_length is None :return None
            tret.value.sern=self.ReadRawBytes(compiled_bytes_length)
            if tret.value.sern is None : return None
            self.id_map[cid]=tret    
            return tret 
      def   ReadWasmMemory(self):
            cid=self.next_id
            self.next_id+=1 
            tret=GenericObject()
            tret.cid=cid    
            tret.value=WasmModule()
            tret.instance_type="WASM_MEMORY_TYPE"
            tret.value.maxpages=self.ReadZigZag()
            if tret.value.maxpages is None: return None
            stag=self.ReadTag()
            if stag != SerializationTag.kSharedArrayBuffer: return None
            kbuf=self.ReadJSArrayBuffer(True)
            if kbuf is None: return None
            self.abuf.value=kbuf.value
            self.id_map[cid]=tret    
            return tret    
      def ReadHostObject(self):
          if self.delegate is None: return None
          cid=self.next_id
          self.next_id+=1        
          obj=self.delegate.ReadHostObject()
          if obj is None: return None
          tret=GenericObject()
          tret.cid=cid  
          tret.instance_type="JS_OBJECT_TYPE"
          tret.value=obj
          self.id_map[cid]=tret    
          return tret 
      def ReadJSObjectProperties(self,jsobj,endtag,can_use_transitions):
          num=0
          if can_use_transitions:
              transitioning =True
              while transitioning:
                  tag=self.PeekTag()
                  if tag is None: return None
                  if tag == endtag:
                      self.ConsumeTag(tag)
                      return num
                  transitioning=False # no support for it?   everything is faked out anyway
          while True:        
            tag=self.PeekTag()
            if tag is None: return None
            if tag == endtag:
               self.ConsumeTag(tag)
               return num
            key=self.ReadObject()
            if key is None: return None
            if not( key.isString or key.isNumber) : 
                 print(key)
                 print(key.instance_type)
                 print(key.isString)
                 print(key.isNumber)
                 print ("Invalid object key - not str or num")
                 import sys
                 sys.exit(1)
                 return None
            value=self.ReadObject()
            if value is None: return None
            jsobj.value[key.value]=value
            num=num+1
          print ("Should not reach here")
          return num     
      def  HasObjectWithID(self,oid):
          return (oid in self.id_map)
      def GetObjectWithID(self,oid):
          if oid not in self.id_map: return None
          obj=self.id_map[oid]
          ret=GenericObject()
          ret.isJSReceiver=True
          ret.value=obj
          ret.instance_type="JS_OBJECT_TYPE"
          ret.idn=oid
          ret.cid=oid
          return ret
      def ReadValue(self):
          if self.vers>0:
              return self.ReadObject()
          else:
              return self.ReadObjectUsingEntireBufferForLegacyFormat()
                      
      def   ReadObjectUsingEntireBufferForLegacyFormat(self):
          stack=[]
          while self.ptr<len(self.buf):
                tag=self.PeekTag()
                if tag is None:break
                new_object=None
                if tag==SerializationTag.kEndJSObject:
                    num_props=self.ReadVarint()
                    if num_props is None or (len(stack)/2)<num_props: return None
                    new_object=JSObject()
                    for i in range(num_props):
                        key=stack.pop() #TODO: maybe backwards?
                        val=stack.pop()
                        new_object.propdict[key.value]=val
                elif SerializationTag.kEndSparseJSArray:    
                     num_props=self.ReadVarint()
                     if num_props is None: return None
                     length=self.ReadVarint()
                     if length is None: return None
                     new_object=GenericObject()
                     new_object.instance_type="JS_ARRAY_TYPE" 
                     new_object.cid=self.next_id
                     self.next_id +=1
                     new_object.value={}
                     for i in range(num_props):
                        key=stack.pop() #TODO: maybe backwards?
                        val=stack.pop()
                        new_object.value[key.value]=val
                elif  SerializationTag.kEndDenseJSArray:
                    return None
                else:
                    new_object=self.ReadObject()
                    if new_object is None: return None
                stack.append(new_object)
          self.ptr=len(self.buf)
          if len(stack) !=1: return None
          return stack[0]
          
          
kWireFormatVersion=18
version0Tags = [35, 64, 68, 73,  78,  82, 83, 85, 91, 98, 102, 108, 123];
def IsByteSwappedWiredData(data):
    if len(data)<4: return True
    if data[0]==kVersionTag:
        if kWireFormatVersion<35:
            if data[1]<35: return False
            return True
        return data[1] in version0Tags
    if data[1]==kVersionTag:
       return data[0]!=kVersionTag
    return True   
def SwapWiredDataIfNeeded(data):
    if not  IsByteSwappedWiredData(data): return data 
    ret=array.array('B',[])
    gt=None
    for bt in data:
        if gt is not None:
            ret.append(bt)
            ret.append(gt)
            gt=None
        else:
            gt=bt
    return ret        

def SSVNullValue():
    dat=SerializedScriptValue(array.array('B',[0xFF, 17, 0xFF, 13, ord('0'), 0x00]))
    return dat
    
kMinVersionForSeparateEnvelope = 16    

class SerializedScriptValue(object):
    def __init__(self,data):
        self.buf=SwapWiredDataIfNeeded(data)
        self.ptr=0
        
        self.image_bitmap_contents_array=set([])
        self.array_buffer_contents_array=set([])
        self.shared_array_buffers_contents=[]
        self.wasmmods=[]
        
    def  SetImageBitmapContentsArray(self,cont):
        self.image_bitmap_contents_array=cont
    def ToWireString(self):
        return self.buf.tostring()+'\0'
    def TransferImageBitmaps (self,bmaps):
        self.image_bitmap_contents_array=set(bmaps)
    def TransferOffscreenCanvas(self,canvases):
         pass # not sure what this does?    
    def TransferArrayBuffers(self, buffers):
        self.array_buffer_contents_array =set(buffers)
    def CloneSharedArrayBuffers(self, shared):
        for buf in shared:
            self.shared_array_buffers_contents.append(buf[:])    
    def HasPackedContents(self):
        return len(self.image_bitmap_contents_array)>0 or len(self.array_buffer_contents_array) >0 or len(self.shared_array_buffers_contents)>0
        
    def ReadVersionEnvelope(self):
        if self.buf is None: return (0,0)
        if len(self.buf)==0: return (0,0)
        if self.buf[0] !=kVersionTag: return (0,0)
        i=1
        shift=0
        version=0
        while True:
            if i>=len(self.buf): return (0,0)
            byt=self.buf[i]
            version |=((byt&0x7f)<<shift)
            shift +=7
            has_another_byte= (byt&0x80)
            i=i+1
            if has_another_byte==0: break
        if version< kMinVersionForSeparateEnvelope: return (0,0)
        return (i,version)    

class ImageSerializationTag:
  kEndTag = 0
  kCanvasColorSpaceTag = 1
  kCanvasPixelFormatTag = 2
  kImageDataStorageFormatTag = 3
  kOriginCleanTag = 4
  kIsPremultipliedTag = 5
  kCanvasOpacityModeTag = 6
  kLast = 6

class BlobDataHandle:
    def __init__(self, uid, tp,sz):
        self.uuid=uid
        self.tp=tp
        selsf.size=sz
class Blob:        
     def __init__(self,bdh): # we don't deal with blobs, not really
         self.bdh=bdh   
         
class BlobData(object):
    def __init__(self):
        self.is_file=False
        self.key=-1
        self.type=""
        self.size=0 #for blobs
        self.filename=""
                 
class DomPoint:
    def __init__(self,x,y,z,w):
        self.x=x
        self.y=y
        self.z=z
        self.w=w
class DomRect:
    def __init__(self,x,y,z,w):
        self.x=x
        self.y=y
        self.width=z
        self.height=w 
class DomQuad:
    def __init__(self):
        self.pts=[]
class DomMatr:
    def __init__(self):
        self.dbls=[]
class OffscreenCanvasTransfer:
    def __init__(self,width,height,canvas_id,client_id,sink_id):
        self.width=width
        self.height=height
        self.canvas_id=canvas_id
        self.client_id=client_id
        self.sink_id=sink_id
class DMFile:
    def __init__(self,path,name,relative_path,uuid,tp,has_snap,size,lastmod,bh):
        self.path=path
        self.name=name
        self.relative_path=relative_path
        self.uuid=uuid
        self.tp=tp
        self.has_snapshot=has_snap
        self.size=size
        self.lastmod=lastmod
        self.blobhandle=bh

PrintLevel=0
def printl(lv,*args):
    if lv<=  PrintLevel:
        print(*args)      
        
class V8Deserializer(object):
    def __init__(self, data):
        self.ssv=SerializedScriptValue(data)
        self.deserializer=ValueDeserializer(self.ssv.buf,self)  
        self.bdh={} 
        self.blobinfo=[] 
        self.imaps=[]
    def Deserialize(self):
        #print(self.ssv.buf)
        env_size,ver=self.ssv.ReadVersionEnvelope()   
        if env_size>0:
           self.deserializer.ReadRawBytes(env_size)
        else:
            if ver !=0: return None
        vhead=self.deserializer.ReadHeader()
        if vhead is None: return None
        if ver ==0: ver=vhead
        self.version=ver
        self.Transfer()
        value=self.deserializer.ReadValue()
        if value is None: return None
        return value
    def ReadUint32(self):
        return self.deserializer.ReadUint32()
    def ReadUint64(self):
        return self.deserializer.ReadUint64()
    def ReadDouble(self):
        return self.deserializer.ReadDouble()
    def ReadRawBytes(self,sz):
        return   self.deserializer.ReadRawBytes(sz)
    def ReadUTF8String(self):
        length=self.ReadUint32()
        if length is None: return None
        bts=self.ReadRawBytes(length)
        if bts is None: return None
        return bts.tostring().decode('utf-8')
        
    def GetOrCreateBlobDataHandle(self,uuid,tp,sz):
        if uid in self.bdh: return self.bdh[uid]
        if len(uid)==0: return None
        self.bdh[uid]= BlobDataHandle(uid,tp,sz)
        return self.bdh[uid]
        
    def ReadDOMObject(self, tag):
        if tag== kBlobTag:
            if self.version<3: return None
            uuid=self.ReadUTF8String()
            if uuid is None: return None
            tp=self.ReadUTF8String()
            if tp is None: return None
            size=self.ReadUint64()
            if size is None: return None
            bdh=self.GetOrCreateBlobDataHandle(uuid,tp,size)
            if bdh is None: return None
            return Blob(bdh)      
        elif tag== kBlobIndexTag:   
            if self.version<6: return None
            index=self.ReadUint32()
            printl(6,"Blobi: {}".format(index))
            if index is None: return None
            printl(6,"Blobinf: {}".format(self.blobinfo))
            if index>=len(self.blobinfo): return {"blobIndex":index}#None #todo - the blob data is not read yet.... 
            return self.blobinfo[index]
        elif tag== kFileTag:  
            return self.ReadFile() 
        elif tag== kFileIndexTag:   
            return self.ReadFileIndex()
        elif tag== kFileListTag:   
            length=self.ReadUint32()
            if length is None: return None
            flist=[]
            for a in range(length):
               fl=self.ReadFile()
               if fl is None: return None
               flist.append(fl)
            return flist    
        elif tag== kFileListIndexTag:
            length=self.ReadUint32()
            if length is None: return None
            flist=[]
            for a in range(length):
               fl=self.ReadFileIndex()
               if fl is None: return None
               flist.append(fl)
            return flist      
        elif tag== kImageBitmapTag:
           ccs=0
           cpf=0
           com=0
           orclean=0
           prem=0             
           if self.version>=18:
               isDone=False
               while not isDone:
                   itag=self.ReadUint32()
                   if itag is None: return None
                   if itag==ImageSerializationTag.kEndTag:
                       isDone=True
                       break
                   elif  itag==ImageSerializationTag.kCanvasColorSpaceTag:   
                       ccs=self.ReadUint32()
                       if ccs is None: return None
                   elif  itag==ImageSerializationTag.kCanvasPixelFormatTag :
                       cpf=self.ReadUint32()
                       if cpf is None: return None
                   elif  itag==ImageSerializationTag.kCanvasOpacityModeTag :
                       com=self.ReadUint32()
                       if com is None: return None
                   elif  itag==ImageSerializationTag.kOriginCleanTag :
                        orclean=self.ReadUint32()
                        if orclean is None or orclean>1: return None                      
                   elif  itag==ImageSerializationTag.kIsPremultipliedTag :
                       prem=self.ReadUint32()
                       if prem is None or pre >1: return None
                   else: 
                       print("NoReachImg")
                       return None
           else:
              com=self.ReadUint32()
              if com is None: return None
              orclean=self.ReadUint32()
              if orclean is None or orclean>1: return None          
           width = self.ReadUint32()
           if width is None: return None
           height =self.ReadUint32()
           if height is None: return None 
           blen=self.ReadUint32()
           if blen is None: return None
           bts=self.ReadRawBytes(blen)
           img={}
           img["bytes"]=bts
           img["width"]=width
           img["height"]=height
           img["CanvasColorSpace"]=ccs
           img["CanvasPixelFormat"]=cpf
           img["CanvasOpacityMode"]=com
           img["isPrem"]=prem
           img["orcl"]=orclean
           return img
        elif tag== kImageBitmapTransferTag: 
            index=self.ReadUint32()
            if index is None: return None
            if len(self.imaps)<=index: return None
            return self.imaps[index]
        elif tag== kImageDataTag:   
           ccs=0
           ids=0
           orclean=0
           prem=0 
           if self.version>=18:
               isDone=False
               while not isDone:
                   itag=self.ReadUint32()
                   if itag is None: return None
                   if itag==ImageSerializationTag.kEndTag:
                       isDone=True
                       break
                   elif  itag==ImageSerializationTag.kCanvasColorSpaceTag:   
                       ccs=self.ReadUint32()
                       if ccs is None: return None
                   elif  itag==ImageSerializationTag.kImageDataStorageFormatTag :
                       ids=self.ReadUint32()
                       if ids is None: return None
                   else: 
                       print("NoReachImg")
                       return None         
           width = self.ReadUint32()
           if width is None: return None
           height =self.ReadUint32()
           if height is None: return None 
           blen=self.ReadUint32()
           if blen is None: return None
           bts=self.ReadRawBytes(blen)
           img={}
           img["bytes"]=bts
           img["width"]=width
           img["height"]=height
           img["CanvasColorSpace"]=ccs
           img["ImageDataStorageFormat"]=ids
           return img
            
        elif tag== kDOMPointTag:
            x=self.ReadDouble()
            if x is None:return None
            y=self.ReadDouble()
            if y is None:return None
            z=self.ReadDouble()
            if z is None:return None
            w=self.ReadDouble()
            if w is None:return None
            return DomPoint(x,y,z,w) 
        elif tag== kDOMPointReadOnlyTag: 
            x=self.ReadDouble()
            if x is None:return None
            y=self.ReadDouble()
            if y is None:return None
            z=self.ReadDouble()
            if z is None:return None
            w=self.ReadDouble()
            if w is None:return None
            return DomPoint(x,y,z,w)              
        elif tag== kDOMRectTag or tag==kDOMRectReadOnlyTag: 
            x=self.ReadDouble()
            if x is None:return None
            y=self.ReadDouble()
            if y is None:return None
            z=self.ReadDouble()
            if z is None:return None
            w=self.ReadDouble()
            if w is None:return None
            return DomRect(x,y,z,w)               
        elif tag== kDOMQuadTag:  
            ret=DomQuad()
            for r in range(4):
                x=self.ReadDouble()
                if x is None:return None
                y=self.ReadDouble()
                if y is None:return None
                z=self.ReadDouble()
                if z is None:return None
                w=self.ReadDouble()
                if w is None:return None
                ret.pts.append(DomPoint(x,y,z,w))
            return ret    
        elif tag== kDOMMatrix2DTag or tag==kDOMMatrix2DReadOnlyTag: 
            ret=DomMatr()
            for  r in range(6):
                d=self.ReadDouble()
                if d is None: return None
                ret.dbls.append(d)
            return ret    
        elif tag== kDOMMatrixTag or tag==kDOMMatrixReadOnlyTag:   
            ret=DomMatr()
            for  r in range(16):
                d=self.ReadDouble()
                if d is None: return None
                ret.dbls.append(d)
            return ret           
        elif tag== kMessagePortTag:  
            index=self.ReadUint32()
            if index is None:return None 
            return index
        elif tag== kOffscreenCanvasTransferTag: 
            width=self.ReadUint32()
            if width is None: return None
            
            height=self.ReadUint32()
            if height is None:return None
            canvas_id=self.ReadUint32()
            if canvas_id is None :return None
            client_id=self.ReadUint32()
            if client_id is None : return None
            sink_id=self.ReadUint32()
            if sink_id is None: return None
            return OffscreenCanvasTransfer(width,height,canvas_id,client_id,sink_id)
        else:
            return None
    def ReadFile(self):
        if self.version <3:return None
        path=self.ReadUtf8String()
        if  path is None: return None
        name=""
        relative_path=""
        if self.version>=4:
            name=self.ReadUTF8String()
            if name is None: return None
            relative_path=self.ReadUTF8String()
            if relative_path is None: return None
        uuid=self.ReadUTF8String()
        if uuid is None: return None
        tp=self.ReadUtf8String()
        if tp is None: return None
        has_snap=0
        if self.version>=4:   
            has_snap=self.ReadUint32()
            if has_snap is None: return None
        size=0
        lastmod=0.0    
        if has_snap>0:
           size=self.ReadUint64()
           if size is None:return None
           lastmod=self.ReadDouble()
           if lastmod is None: return None
           if self.version <8:
               lastmod *= 1000
        is_uv=1
        if self.version>=7:
            is_uv=self.ReadUint32()
            if is_uv is None: return None
        bh=self.GetOrCreateBlobDataHandle(uuid,tp,-1)
        if bh is None: return None
        return DMFile(path,name,relative_path,uuid,tp,has_snap,size,lastmod,bh)    
    def Transfer(self):
        pass #TODO?
       
    def ReadFileIndex(self):
        if self.version <6: return None
        index=self.ReadUint32()
        if index is None: return None
        if index>=len(self.blobinfo): return None
        return self.blobinfo[index] #should be file...
    def ReadHostObject(self):    
        tag=kVersionTag
        tag=self.deserializer.ReadTag()
        if tag is None: return None
        wrp=self.ReadDOMObject(tag)
        return wrp
    def GetWasmModuleFromId(self,oid):
      if self.ssv.wasmmods is None: return None
      if oid >=len(self.ssv.wasmmods): 
          return None
      return self.ssv.wasmmods[oid]    
    def GetSharedArrayBufferFromId(self,aid):
        if self.ssv.shared_array_buffers_contents is None: return None
        if aid>=len(self.ssv.shared_array_buffers_contents): return None
        return self.ssv.shared_array_buffers_contents[aid]

class IndexMeta(object):
    def __init__(self):
        self.name=''
        self.unique=False
        self.keyPath=None
        self.multiEntry=False 
class IndexData(object):
    def __init__(self):
       self.iid=0
       self.index_key=None
       self.seq_num=0
       self.primary_key=None
       self.version=-1
       self.primary_ref_key=None
       
       
            
class ObjectStore(object):
    def __init__(self):
        self.name=""
        self.keyPath=""
        self.autoIncr=False
        self.isEvictable=False
        self.lastVersion=0
        self.maxIndexId=0
        self.hasKeyPath=True
        self.keyGenCurrent=0
        self.indices={} 
        self.objects={}   
        self.objExists={}  
        self.rawBlobs={}         
        self.indexEntries={}
class IndexedDatabase(object): #single db
    def __init__(self,nm,ori):
        self.name=nm
        self.origin=ori
        self.maxObjectID=0
        self.idbVersion=0
        self.blobKeyGen=0
        self.obFreeList={}
        self.indexFreeList={}
        self.objectStores={}

    def ProcessParsedKeyValue(self,prefix_a,slice_a,slice_val):
         ctp=prefix_a.ctype()
         if ctp==KeyPrefix.DATABASE_METADATA:
             (ok, type_byte_a)=DecodeByte(slice_a)
             if not ok: 
                 print(u"Invalid_Database_Metadata")
                 return 
             if (type_byte_a == 0):
                 (dm,vl)=DecodeString(slice_val)
                 if dm: self.origin=vl
                 return
             if (type_byte_a == 1):
                 (dm,vl)=DecodeString(slice_val)
                 if dm: self.name=vl
                 return
             if (type_byte_a == 2):
                 (dm,vl)=DecodeString(slice_val)
                 if dm: self.idbVersion=vl
                 return
             if (type_byte_a == 3):
                 (dm,vl)=DecodeVarInt(slice_val)
                 if dm: self.maxObjectID=vl
                 return
             if (type_byte_a == 4):
                 (dm,vl)=DecodeVarInt(slice_val)
                 if dm: self.idbVersion=vl
                 return
             if (type_byte_a == 5):
                 (dm,vl)=DecodeVarInt(slice_val)
                 if dm: self.blobKeyGen=vl
                 return
             if (type_byte_a == 150): #obsolete? 
                 (dm,vl)=DecodeVarInt(slice_a)
                 if dm: 
                      if not vl in self.obFreeList: self.obFreeList[vl]=''
                 return            
             if (type_byte_a == 151):
                 (dm,oid)=DecodeVarInt(slice_a)
                 (dm,iid)=DecodeVarInt(slice_a)
                 if dm:
                   self.indexFreeList["{}_{}".format(oid,iid)]=''
                 return                
             if (type_byte_a == 200): #obsolete? 
                 (dm,onm)=DecodeStringWithLength(slice_a)
                 if not dm: return
                 (dm,vl)=DecodeInt(slice_val)
                 if dm: self.obFreeList[vl]=onm
                 return                        
             if (type_byte_a == 201):
                 (dm,oid)=DecodeVarInt(slice_a)                      
                 (dm,inm)=DecodeStringWithLength(slice_a)
                 (dm,iid)=DecodeInt(slice_val)
                 if dm: self.indexFreeList["{}_{}".format(oid,iid)]=inm
                 return
             if type_byte_a == kObjectStoreMetaDataTypeByte:   
                (ok,obj_store_id)=DecodeByte(slice_a)
                if not ok: 
                    print(u"Invalid_Metadata_Database_ObjectStore")
                    return 
                if not  obj_store_id in self.objectStores:
                    self.objectStores[obj_store_id]=ObjectStore()
                (ok,oid_type)=DecodeByte(slice_a)
                if not ok: 
                    print(u"Could not read oid entry type")
                    return
                if oid_type==0:
                   (dm,nm)=DecodeString(slice_val)
                   if dm:  self.objectStores[obj_store_id].name=nm
                   return
                if oid_type==1:
                   (dm,nm)=DecodeIDBKeyPath(slice_val)
                   if dm:  self.objectStores[obj_store_id].keyPath=nm
                   return
                if oid_type==2:
                   (dm,nm)=DecodeBool(slice_val)
                   if dm:  self.objectStores[obj_store_id].autoIncr=nm
                   return
                if oid_type==3:
                   (dm,nm)=DecodeBool(slice_val)
                   if dm:  self.objectStores[obj_store_id].is_evictable=nm
                   return
                if oid_type==4:
                   (dm,nm)=DecodeInt(slice_val)
                   if dm:  self.objectStores[obj_store_id].lastVersion=nm
                   return
                if oid_type==5:
                   (dm,nm)=DecodeInt(slice_val)
                   if dm:  self.objectStores[obj_store_id].maxIndexId=nm
                   return
                if oid_type==6:
                   (dm,nm)=DecodeBool(slice_val)
                   if dm:  self.objectStores[obj_store_id].hasKeyPath=nm
                   return
                if oid_type==7:
                   (dm,nm)=DecodeInt(slice_val)
                   if dm:  self.objectStores[obj_store_id].keyGenCurrent=nm
                   return
             if  type_byte_a == kIndexMetaDataTypeByte:
                (ok,oid)=DecodeVarInt(slice_a)
                if not ok: return 
                if not  oid in self.objectStores:
                    self.objectStores[oid]=ObjectStore()
                (ok,iid)=DecodeVarInt(slice_a)
                if not ok: return 
                if not iid in self.objectStores[oid].indices:
                    self.objectStores[oid].indices[iid]=IndexMeta()
                acti= self.objectStores[oid].indices[iid]
                (ok,var_a)=DecodeByte(slice_a)
                
                if not ok: return 
                if var_a==0:
                   (dm,nm)=DecodeString(slice_val)
                   if dm:  acti.name=nm
                   return    
                if var_a==1:
                   (dm,nm)=DecodeBool(slice_val)
                   if dm:  acti.unique=nm
                   return    
                if var_a==2:
                   (dm,nm)=DecodeIDBKeyPath(slice_val)
                   if dm:  acti.keyPath=nm
                   return  
                if var_a==3:
                   (dm,nm)=DecodeBool(slice_val)
                   if dm:  acti.multiEntry=nm
                   return                     
                   
                                                                                        
             elif type_byte_a == kObjectStoreFreeListTypeByte:
                (ok,var_a)=DecodeVarInt(slice_a)
                if not ok: return u"Invalid_ObjectstoreFreelistMeta"
                return u"Metadata_ObjectStoreFreeList_{}".format(var_a)
             elif type_byte_a == kIndexFreeListTypeByte:
                (ok,oid_a)=DecodeVarInt(slice_a)
                if not ok: return u"Invalid_Metadata_IndexFreeList"
                (ok,iid_a)=DecodeVarInt(slice_a)
                if not ok: return u"Invalid_Metadata_IndexFreeList"
                return "Metadata_Index_Freelist_{}_{}".format(oid_a,iid_a)
             elif type_byte_a == kObjectStoreNamesTypeByte:
                (ok,dname_a)=DecodeStringWithLength(slice_a)
                if not ok: return u"Invalid_Metadata_DBNames"
                return u"Metadata_DBNames_{}".format(dname_a)      
             elif type_byte_a == kIndexNamesKeyTypeByte:
                (ok,oid_a)=DecodeVarInt(slice_a)
                if not ok: return u"Invalid_Metadata_IndexNames"
                (ok,dname_a)=DecodeStringWithLength(slice_a)
                if not ok: return u"Invalid_Metadata_IndexNames"
                return u"Metadata_IndexNames_{}_{}".format(oid_a,dname_a)
             else: 
                 return u"Invalid_Metatype"
         elif ctp==KeyPrefix.OBJECT_STORE_DATA:
              if not prefix_a.object_store_id in self.objectStores:
                  self.objectStores[prefix_a.object_store_id]=ObjectStore()
              if (len(slice_a)==0):
                print(u"Degenerate_Key_{}".format(repr(prefix_a)))
                return
              (ok,key)=DecodeIDBKey(slice_a)
              if not ok: 
                  print( u"Invalid_Object_Store_Key" )  
                  return
              (ok, ver) = DecodeVarInt(slice_val)
              des=V8Deserializer(slice_val)
              val=des.Deserialize()
              self.objectStores[prefix_a.object_store_id].objects[key]=val
              return
         elif ctp==KeyPrefix.EXISTS_ENTRY:  
           if not prefix_a.object_store_id in self.objectStores:
                  self.objectStores[prefix_a.object_store_id]=ObjectStore()            
           if (len(slice_a)==0):
            print("Degenerate EXISTS key")  
            return
           (ok,key)=DecodeIDBKey(slice_a)
           if not ok:
               print ( u"Invalid_Exists_Entry_Key" ) 
               return  
           #print("huh")    
           #print(repr(prefix_a))     
           #print(slice_val)
           (ok, ver)=DecodeInt(slice_val)      
           self.objectStores[prefix_a.object_store_id].objExists[key]=ver     
           return
         elif ctp==KeyPrefix.BLOB_ENTRY:    
           if (len(slice_a)==0 ):
             print(u"Degenerate_Blob")
             return
           if not prefix_a.object_store_id in self.objectStores:
                  self.objectStores[prefix_a.object_store_id]=ObjectStore()            
            
           (ok,key)=DecodeIDBKey(slice_a)
           if not ok:  
              print( u"Invalid_Blob_Entry_Key")
              return
           blbs=[]
           while True:
              nxt=BlobData()
              (ok, ifl)=DecodeBool(slice_val)
              if not ok: break
              nxt.is_file=ifl
              (ok, bk)=DecodeVarInt(slice_val)
              if not ok: break
              nxt.key=bk
              (ok, stt)=DecodeStringWithLength(slice_val)
              if not ok: break
              nxt.type=stt
              if ifl:
                (ok,fn)=DecodeStringWithLength(slice_val)
                if not ok: break
                nxt.filename=fn
              else:
                (ok,sz)=DecodeVarInt(slice_val)
                if not ok: break
                nxt.size=sz
              blbs.append(nxt)    
           self.objectStores[prefix_a.object_store_id].rawBlobs[key]=blbs
         elif ctp==KeyPrefix.INDEX_DATA:  
           iid=prefix_a.index_id  
           if (len(slice_a)==0):
             print( u"Degenerate_Index_Key_{}")
             return
           (ok,index_key)=DecodeIDBKey(slice_a)  
           if not ok: 
              print( u"Invalid_Index_Data_Key")
              return 
              
           (ok, sequence_number_a) = DecodeVarInt(slice_a)
           if not ok: 
              print(  u"Index_Data_{}".format(repr(key)))
              return
           (ok,prim_key)=DecodeIDBKey(slice_a) 
           if not ok: return
           (ok, vers)=DecodeVarInt(slice_val)
           if not ok: return
           (ok, out_key)=DecodeIDBKey(slice_val)
           idd=IndexData()
           idd.iid=iid
           idd.index_key=index_key
           idd.seq_num=sequence_number_a
           idd.primary_key=prim_key
           idd.version=vers
           idd.primary_ref_key=out_key
           if not prefix_a.object_store_id in self.objectStores:
                  self.objectStores[prefix_a.object_store_id]=ObjectStore()  
           self.objectStores[prefix_a.object_store_id].indexEntries[iid]=idd                 
         else:
          print( u"Invalid_Key" ) 
          print(ctp)
          print(prefix_a)
class IndexedPool(object):
    
    def __init__(self):
        self.blob_data={}
        self.databases={}
        self.schemaVersion=-1
        self.dataVersion=0
        self.primaryBlobJournal=''
        self.liveBlobJournal=''
        self.earliestSweep=0
        self.dbFree={}
        self.databases={}

    def ProcessKeyValue(self,key,value):
      try:
       slice_a=array.array('B',[ord(i) for i in key])#a[:]
       slice_val=array.array('B',[ord(i) for i in value])
      except:
       slice_a=array.array('B',[i for i in key])#a[:]
       slice_val=array.array('B',[i for i in value])
      prefix_a=KeyPrefix()
      ok_a = prefix_a.Decode(slice_a)
      if not ok_a:
          print("Invalid key prefix")
          return
      ctp=prefix_a.ctype()
      if ctp== KeyPrefix.GLOBAL_METADATA: 
         (ok, type_byte_a)=DecodeByte(slice_a)
         if not ok: 
              print("Invalid_Prefix_Type byte")
              return
         if type_byte_a == kSchemaVersionTypeByte:
             (dm,vl)=DecodeInt(slice_val)
             self.schemaVersion=vl
         if type_byte_a == kMaxDatabaseIdTypeByte:
             (dm,vl)=DecodeInt(slice_val)
             self.maxDatabaseID=vl
         if type_byte_a == kDataVersionTypeByte:
             (dm,vl)=DecodeInt(slice_val)
             self.dataVersion=vl
         if type_byte_a == kBlobJournalTypeByte:
             self.primaryBlobJournal=value                                       
         if type_byte_a == kLiveBlobJournalTypeByte:
             self.liveBlobJournal=value        
         if type_byte_a == kEarliestSweepTimeTypeByte:
             (dm,vl)=DecodeInt(slice_val)
             self.earliestSweep=vl                                      
            
         if type_byte_a == kDatabaseFreeListTypeByte:
            (ok,var_a)=DecodeVarInt(slice_a)
            if not ok: 
                print ("Invalid Freelist data")
                return 
            self.dbFree[var_a]=value    
         elif type_byte_a == kDatabaseNameTypeByte:
            (ok,origin_a)=DecodeStringWithLength(slice_a)
            if not ok: 
                print("Invalid_Metadata_Name")
                return 
            (ok,dname_a)=DecodeStringWithLength(slice_a)
            if not ok: 
                print("Invalid_Metadata_Name(2)")
                return 
            (dm,vl)=DecodeVarInt(slice_val)
            if vl in self.databases:
                print("Duplicate db id {} ?".format(vl))
                return
            self.databases[vl]=IndexedDatabase(dname_a,origin_a)
            return
      else:
          
         if prefix_a.database_id not in self.databases:
             self.databases[prefix_a.database_id]=IndexedDatabase('<>','<>')
         self.databases[prefix_a.database_id].ProcessParsedKeyValue(prefix_a,slice_a,slice_val)    
         return
      return u"Not reached -r2"
      

"""
void V8ScriptValueDeserializer::Transfer() {
  // Thre's nothing to transfer if the deserializer was not given an unpacked
  // value.
  if (!unpacked_value_)
    return;

  v8::Isolate* isolate = script_state_->GetIsolate();
  v8::Local<v8::Context> context = script_state_->GetContext();
  v8::Local<v8::Object> creation_context = context->Global();

  // Transfer array buffers.
  const auto& array_buffers = unpacked_value_->ArrayBuffers();
  for (unsigned i = 0; i < array_buffers.size(); i++) {
    DOMArrayBufferBase* array_buffer = array_buffers.at(i);
    v8::Local<v8::Value> wrapper =
        ToV8(array_buffer, creation_context, isolate);
    if (array_buffer->IsShared()) {
      
"""
