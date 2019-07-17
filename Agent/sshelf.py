from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
import sys
import struct
from Crypto.Util.number import bytes_to_long
from Crypto.PublicKey import RSA
from Crypto.PublicKey import DSA
import re
def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value=value.decode('utf-8')
    value = re.sub('[^\w\s-]', '_', value).strip()
    value = re.sub('[-\s]+', '_', value)
    return value
fl=open(sys.argv[1], 'rb')
elffile = ELFFile(fl)
print("Segments: {}".format(elffile.num_segments()) )

dprint=False

class Segment(object):
    virtMem=None
    offset=None
    sz=None
    data=None
    def __init__(self,segm,fl):
        self.virtMem=segm['p_vaddr']
        self.offset=segm['p_offset']
        self.sz=segm['p_memsz']
        fl.seek(self.offset)
        self.data=fl.read(self.sz)
        #print(data)

"""struct name {								\
	struct type *tqh_first;	/* first element */			\
	struct type **tqh_last;	/* addr of last next element */		\
}"""

class idtable(object):
    
    def __init__(self,bytepack):
        pckstr="@iPP"
        ln=struct.calcsize(pckstr)
        up=struct.unpack(pckstr,bytepack[:ln])
        self.nentries=up[0]
        self.first_ptr=up[1]
        self.last_pptr=up[2]
"""
typedef struct identity {
	TAILQ_ENTRY(identity) next;
	struct sshkey *key;
	char *comment;
	char *provider;
	time_t death;
	u_int confirm;
} Identity;
"""

class identity(object):
    def __init__(self,bytepack):
        pckstr="@PPPPPQI"
        ln=struct.calcsize(pckstr)
        up=struct.unpack(pckstr,bytepack[:ln])
        self.next_ptr=up[0]
        self.prev_ptr=up[1]
        self.key_ptr=up[2]
        self.comment=up[3]
        self.provider=up[4]
        self.dth=up[5]
        self.confirm=up[6]
        
"""
struct sshkey {
	int	 type;
	int	 flags;
	RSA	*rsa;
	DSA	*dsa;
	int	 ecdsa_nid;	/* NID of curve */
	EC_KEY	*ecdsa;
	u_char	*ed25519_sk;
	u_char	*ed25519_pk;
	char	*xmss_name;
	char	*xmss_filename;	/* for state file updates */
	void	*xmss_state;	/* depends on xmss_name, opaque */
	u_char	*xmss_sk;
	u_char	*xmss_pk;
	struct sshkey_cert *cert;
};
""" 
"""
struct ec_key_st {
    const EC_KEY_METHOD *meth;
    ENGINE *engine;
    int version;
    EC_GROUP *group;
    EC_POINT *pub_key;
    BIGNUM *priv_key;
    unsigned int enc_flag;
    point_conversion_form_t conv_form;
    CRYPTO_REF_COUNT references;
    int flags;
    CRYPTO_EX_DATA ex_data;
    CRYPTO_RWLOCK *lock;
};
"""
class sshkey(object):
    def __init__(self,bytepack):
        pckstr="@iiPPiPPPPPPPPP"
        ln=struct.calcsize(pckstr)
        up=struct.unpack(pckstr,bytepack[:ln])
        self.type=up[0]
        self.flags=up[1]
        self.rsa=up[2]
        self.dsa=up[3]
        
class Virtmem(object):
    segms=[]
    def __init__(self,efile,fl):
        self.segms=[]
        self.instances={}
        for segment in elffile.iter_segments():
           s=Segment(segment,fl)
           self.segms.append(s)
    def addrInSegm(self,addr):
        for s in self.segms:
            if(addr>=s.virtMem and addr <s.virtMem+s.sz):
                return s
        return None
    def getPtr(self,addr):
        sg=self.addrInSegm(addr)
        if sg is None: return None
        return struct.unpack("@P",sg.data[addr-sg.virtMem:addr-sg.virtMem+8])[0]
    def getInt32(self,addr):
        sg=self.addrInSegm(addr)
        if sg is None: return None
        return struct.unpack("@i",sg.data[addr-sg.virtMem:addr-sg.virtMem+4])[0]
    def getIdtable(self,addr):
        sg=self.addrInSegm(addr)
        if sg is None: return None
        return idtable(sg.data[addr-sg.virtMem:])           
        
    def getIdentity(self,addr):
        sg=self.addrInSegm(addr)
        if sg is None: return None
        return identity(sg.data[addr-sg.virtMem:])   
    def readCstr(self,addr):
        if addr==0 :return '';
        sg=self.addrInSegm(addr)
        if sg is None: return None
        lst=[]
        cnt=addr-sg.virtMem
        while sg.data[cnt]!=0:
            lst.append(sg.data[cnt])
            cnt=cnt+1 
        #print(bytes(lst))    
        return    bytes(lst).decode('utf-8')   
    def regInstance(self,addr,sti):
        if not addr in self.instances:
            self.instances[addr]={}
        self.instances[addr][sti.definition.name]=sti
    def clearInstance(self):
        self.instances={}
    def getInstance(self,addr,name):
        if not addr in self.instances:
            return None
        if not name in self.instances[addr]:
            return None
        return    self.instances[addr][name]         

class InvalidSyntax(Exception):
     pass

class stCondition(object):
    def __init__(self):
        pass
    def validate(self,vm,value):
        return True

class stCondEq(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         ret=(value==self.val)
         return ret
        except:
         return False
            
class stCondNeq(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         ret=(value!=self.val)
         return ret
        except:
         return False        

class stCondGt(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         ret=(value>self.val)
         return ret
        except:
         return False
         
         
class stCondLt(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         ret=(value<self.val)
         return ret
        except:
         return False
         
class stCondGte(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         ret=(value>=self.val)
         return ret
        except:
         return False
         
         
class stCondLte(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         ret=(value<=self.val)
         return ret
        except:
         return False         

class stCondTextPtr(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         s=vm.readCstr(value)
         if (s is None): 
             return False
         return True
        except Exception as e:
         #print(e)   
         return False            


class stCondTextPtrNE(stCondition):
    def __init__(self,val):
       self.val=val
    def validate(self,vm,value):
        try:
         s=vm.readCstr(value)
         if (s is None): 
             return False
         return len(s)>0
        except:
         return False   
               
class stWrap(object):
  def __init__(self,stw,offset):
     self.stw=stw
     self.offset=offset
     
#needs refactoring. Instances?
class stInstance(object):
    def __init__(self,definition):
        self.definition=definition
        self.offset=0
        if definition.primitive:
         self.value=None
        else:
           self.value={} 
           for aname in self.definition.attrs:
               #print(aname)
               self.value[aname]= self.definition.attrs[aname].stw.instanceOf();
    def loadFromBytes(self,bpack):
        try:
           ln=struct.calcsize('@'+self.definition.pstr)
           if(ln>len(bpack)): return None
           tpl=struct.unpack('@'+self.definition.pstr,bpack[:ln])
        except Exception as E:
            print(E)
            return None
        return self.loadFromTuple(tpl)
    def loadFromTuple(self,tpl):
        if tpl is None:return None
        if dprint: print("Typeload {}".format(self.definition.name))
        if len(tpl)==0: return self #void core?
        if self.definition.primitive:
            self.value=tpl[0]
        else:     
          for aname in self.value:
              if dprint: print("Loading {} {}".format(aname,self.value[aname].definition))
              sd=self.definition.attrs[aname]
              self.value[aname].loadFromTuple(tpl[self.definition.attrs[aname].offset:])
              tpl[sd.offset:]
        return self         
    def validate(self,vm):
        return self.definition.validate(vm,self.value)
    def validate_ptr(self,vm,addr):
        sg=vm.addrInSegm(addr)
        if sg is None: return False
        chk=self.loadFromBytes(sg.data[addr-sg.virtMem:])
        if(chk is None): return False
        vm.clearInstance()
        vm.regInstance(addr,self)
        ret=self.validate(vm)
        vm.clearInstance()
        return ret
    def __getitem__(self, name):    
        return self.__getattr__(name)
    def __getattr__(self, name):
        if self.definition.primitive:
            return self.value
        ret=self.value[name]            
        if isinstance(ret,stInstance):
            if ret.definition.primitive:
                return ret.value
        return ret
    def deref(self,val,vm):
        if self.definition.primitive:
            if( isinstance(self.definition,stPointer)):
                return self.definition.deref(vm,self.value)            
            return None
        rt= self.value[val]       
        if(isinstance(rt.definition,stPointer)):
                return rt.definition.deref(vm,rt.value) 
        return None
class stDef(object):
    def __init__(self,name):
        self.name=name
        self.pstr='' 
        self.attrs={} #stWraps
        self.anum=0
        self.complete=False
        self.offset=-1
        self.primitive=False
        self.conditions=[]
    def instanceOf(self):
        ret=stInstance(self)
        return ret 
    def copy(self):
        ret=stDef(self.name)
        ret.pstr=self.pstr
        ret.anum=self.anum
        ret.complete=self.complete
        ret.offset=self.offset
        ret.primitive=self.primitive
        ret.attrs={}
        for nm in self.attrs:
            ret.attrs[nm]=stWrap(self.attrs[nm].stw.copy(),self.attrs[nm].offset)
        return ret    
    def setCondition(self,cond):
        raise InvalidSyntax("cannot impose conditions on compound types")
    
    def validate(self,vm,value):
        if (isinstance(value,stInstance)):
            value=value.value
        for nm in self.attrs:
            if not self.attrs[nm].stw.validate(vm,value[nm]): return False
        return True    
    def consumeDef(self,name,sdef):
        if name in self.attrs:
            raise InvalidSyntax("Duplicate attribute {}".format(name))
        self.pstr=self.pstr+sdef.pstr
        #print(self.pstr+repr(sdef))
        ndf=stWrap(sdef,self.anum) 
        self.anum+=len(sdef.pstr)
        self.attrs[name]=ndf
    def replacePlaceholder(self,name,stdf,lst):
        #print("Repl {}".format(name))
        if self in lst: return
        lst.append(self)
        for an in self.attrs:
            if isinstance(self.attrs[an].stw,Placeholder):
                if self.attrs[an].stw.name==name:
                    coffs=self.attrs[an].offset
                    dlen=len(stdf.pstr)
                    self.pstr=self.pstr[:coffs]+stdf.pstr+self.pstr[coffs:]
                    for nn in self.attrs:
                        if self.attrs[nn].offset>=coffs and nn!=an:
                            self.attrs[nn].offset+=dlen
                    self.attrs[an].stw=stdf
                    self.attrs[an].stw.replacePlaceholder(name,stdf,lst) #for pointers!
            else:
              clen=len(self.attrs[an].stw.pstr)
              self.attrs[an].stw.replacePlaceholder(name,stdf,lst)
              nlen=len(self.attrs[an].stw.pstr)
              if nlen!=clen:
                  coffs=self.attrs[an].offset
                  self.pstr=self.pstr[:coffs]+self.attrs[an].stw.pstr+self.pstr[coffs+clen:]
                  for nn in self.attrs:
                      if self.attrs[nn].offset>coffs:
                          self.attrs[nn].offset+=nlen-clen 
                          
                          
#additional conditions
# |>0| |!0| |text| |textne|
                          
class stBuiltin(stDef):
  def __init__(self,name,pstr):
        super().__init__(name)
        self.primitive=True
        self.pstr=pstr
        self.conditions=[]
  def replacePlaceholder(self,name,stdf,lst):
       pass
  def consumeDef(self,name,sdef):
      pass
  def setCondition(self,cond):
      self.conditions.append(cond)
  def copy(self):
      ret=stBuiltin(self.name, self.pstr)
      ret.conditions=list(self.conditions)
      return ret  
  def validate(self,vm,value):
      if self.pstr=='': return True
      if isinstance(value,stInstance):
           value=value.value      
      for cond in self.conditions:
          if not cond.validate(vm,value): 
               if dprint: print("Failed {} for {} ".format(cond,self.name) )
               return False
      return True          
      
class stPointer(stDef):
   def __init__(self,name,stdf):  #name of our class        
      super().__init__(name+'*')
      self.rname=name
      self.root=stdf
      self.pstr='P'
      self.primitive=True
      self.conditions=[]
   def replacePlaceholder(self,name,stdf,lst):  
      if self in lst: return
      lst.append(self)       
      if dprint: print("Ptr "+self.name+" "+self.rname+" "+name+"  >"+stdf.name)
      if isinstance(self.root,Placeholder) and name==self.rname:
          if dprint: print("rplaced")
          self.root=stdf
      if not isinstance(self.root,Placeholder) and self.root.name!=name:
           self.root.replacePlaceholder(name,stdf,lst)  
   def consumeDef(self,name,sdef):
      pass
   def deref(self,vm,value): 
       if isinstance(value,stInstance):
           value=value.value
       if value is None: return None
       if(value==0): return None
       sg=vm.addrInSegm(value)                   
       if(sg is None) :return None
       if self.rname=='char':
           isTxt=False
           for c in self.conditions:
               if isinstance(c,stCondTextPtr) or isinstance(c,stCondTextPtrNE):
                   isText=True
                   break
           if isText:        
            return vm.readCstr(value)
       dinst=stInstance(self.root)
       dinst.loadFromBytes(sg.data[value-sg.virtMem:])     
       return  dinst   
   def copy(self):
       ret= stPointer(self.rname,self.root)   
       ret.conditions=list(self.conditions)
       return ret
   def setCondition(self,cond):
         self.conditions.append(cond)
   def validate(self,vm,value):
       if isinstance(value,stInstance):
           value=value.value
       if value is None: return False
       for cond in self.conditions:
          if not cond.validate(vm,value): 
              if dprint: print("Failed {} for {} ".format(cond,self.name) )
              return False       
       if value==0: return True
       sg=vm.addrInSegm(value)                   
       if(sg is None) :return False
       inst=vm.getInstance(value,self.root.name)
       if inst is not None:
          return True 
       #print(self.root.name)
       #print(value)
       dinst=stInstance(self.root)
       dinst.loadFromBytes(sg.data[value-sg.virtMem:])
       vm.regInstance(value,dinst)
       return dinst.validate(vm)
       
class Placeholder(object):
    def __init__(self,strname):
        self.name=strname
        self.pstr=''
    def copy(self):
        return Placeholder(self.name)    
    def validate(self,vm):
         return True   
#if isinstance(o, str):

        
class  stParser(object):
   def __init__(self,strng):
       self.strng=strng
       self.pos=0
       self.seps=set([',',';','[',']','|','*']);
       self.defs=set(['struct','class']);
       self.builtins=set(['int','uint','int32','int64','uint64','void','char','uchar','long','float','double','size_t','ssize_t','short','ushort']);
       self.structs={}
   def getBuiltin(self,vtype):
       if vtype=='int':
           return stBuiltin(vtype,'i')
       if vtype=='uint':
           return stBuiltin(vtype,'I')
       if vtype=='int32':
           return stBuiltin('int','i')
       if vtype=='int64':
           return stBuiltin(vtype,'q')
       if vtype=='uint64':
           return stBuiltin(vtype,'Q')           
       if vtype=='void':
           return stBuiltin(vtype,'')
       if vtype=='char':
           return stBuiltin(vtype,'b')
       if vtype=='uchar':
           return stBuiltin(vtype,'B')
       if vtype=='long':
           return stBuiltin(vtype,'l')
       if vtype=='float':
           return stBuiltin(vtype,'f')
       if vtype=='double':
           return stBuiltin(vtype,'d')
       if vtype=='size_t':
           return stBuiltin(vtype,'N')
       if vtype=='ssize_t':
           return stBuiltin(vtype,'n')
       if vtype=='short':
           return stBuiltin(vtype,'h')
       if vtype=='ushort':
           return stBuiltin(vtype,'H')
       return None
                    
   def skipWhitespace(self):
      while self.pos<len(self.strng):
           if self.strng[self.pos].isspace():
               self.pos+=1
           else:
               break    
   def getToken(self):
       if self.pos>len(self.strng): return None
       lst=[]
       self.skipWhitespace()
       while self.pos<len(self.strng):            
          if self.strng[self.pos].isspace() or self.strng[self.pos] in self.seps:
              break
          lst.append(self.strng[self.pos])
          self.pos+=1
       return ''.join(lst)   
   def consumeToken(self):
       return self.getToken()                               
   def peekToken(self):
       opos=self.pos
       tkn=self.getToken()
       self.pos=opos
       return tkn 
   def peekSymbol(self):
       opos=self.pos
       if (self.pos>=len(self.strng)): return None
       self.skipWhitespace()
       if (self.pos>=len(self.strng)): 
           sym=None
       else:
           sym=self.strng[self.pos]
       self.pos=opos    
       return sym
   def consumeSymbol(self):
       self.skipWhitespace()
       if (self.pos>=len(self.strng)): return None
       ret=self.strng[self.pos]
       self.pos+=1
       return ret
   def readNum(self,ntype):
       self.skipWhitespace()
       if (self.pos>=len(self.strng)): return None
       numz=set('0123456789.')
       acc=[]
       while self.pos<len(self.strng) and self.strng[self.pos]in numz:
           acc.append(self.strng[self.pos])
           self.pos=self.pos+1
       return ntype(''.join(acc))
              
   def consumeCondition(self):
       smb=self.consumeSymbol()
       if smb=='|': return None
       if smb=='!':
         return stCondNeq(self.readNum(int))
       if smb=='=':
         return stCondEq(self.readNum(int))         
       if smb=='>':
           if self.peekSymbol()=='=':
               self.consumeSymbol()
               return stCondGte(self.readNum(int))
           else:
               return stCondGt(self.readNum(int))    
       if smb=='<':
           if self.peekSymbol()=='=':
               self.consumeSymbol()
               return stCondLte(self.readNum(int))
           else:
               return stCondLt(self.readNum(int))    
       rm=smb+self.consumeToken()        
       if rm=='text':
           return stCondTextPtr('')
       if rm=='textne':
           return stCondTextPtrNE('')
       return None    
   def getVariable(self): #returns lists of tuples (name, stdef)
       vtype=self.getToken()    
       if vtype in self.builtins:
           stdf=self.getBuiltin(vtype)
       elif vtype in self.structs:
           stdf=self.structs[vtype]
       else: #not found?
           #print("Place "+vtype)
           stdf=Placeholder(vtype)
       nt=self.peekSymbol()
       while nt is not None and nt=='*':
           self.consumeSymbol()
           if dprint: print("Pointering "+stdf.name)
           stdf=stPointer(stdf.name,stdf)
           if dprint: print(stdf.name)
           nt=self.peekSymbol()
       #definition prepared... 
       retvars=[]
       while True:
         varname=self.getToken()
         cstd=stdf.copy()
         numarr=1
         if varname is None: return retvars
         while True:
             smb=self.consumeSymbol()
             if smb==';':
               if numarr ==1:  
                retvars.append((varname,cstd));
               elif numarr>1:
                for i in range(numarr):   
                  retvars.append((varname+"[{}]".format(i),cstd));    
               else:
                   pass   
               return retvars
             if smb==',' :
                if numarr ==1:  
                 retvars.append((varname,cstd));
                elif numarr>1:
                 for i in range(numarr):   
                   retvars.append((varname+"[{}]".format(i),cstd));    
                else:
                   pass   
                break            
             if smb=='[':#array...
                 tkn=self.getToken()
                 if self.consumeSymbol()!=']':
                      raise InvalidSyntax("Array not ending with ] near {0}".format(varname))
                 try:
                   numarr=int(tkn)
                 except:
                      raise InvalidSyntax("Array amount should be int, not {0}".format(tkn))
             if smb=='|':
                 cond=self.consumeCondition()
                 if cond is None:
                     raise InvalidSyntax("Invalid condition near  {0}".format(varname))            
                 if self.consumeSymbol()!='|':
                      raise InvalidSyntax("Condition not ending with | near {0}".format(varname))
                 cstd.setCondition(cond)

   def getDefinition(self):
       token=self.getToken()
       if token is None:#EOF?
           return None
       if token =='':
           return None    
       if token  not in self.defs:
           raise InvalidSyntax("wrong Definition around {0}".format(token))
       name=self.getToken()
       if dprint: print("Loading "+name )
       if name in self.structs:
           raise InvalidSyntax("Duplicate struct  {0}".format(name))
                 
       ndef=stDef(name)
       opn=self.consumeSymbol()
       if opn!='{':
            raise InvalidSyntax("Needs { after {}{}".format(token,name))
       while True:
          if self.pos>=len(self.strng): break
          if self.peekSymbol()=='}':
              self.consumeSymbol()
              break
          lst=self.getVariable ()
          for var in lst:
              ndef.consumeDef(var[0],var[1])
       self.structs[name]=ndef
       for nm in self.structs:
           if dprint: print("Rplacing {} in {}".format(name,nm))
           self.structs[nm].replacePlaceholder(name,ndef,[])
       return   self.structs[name]
   def parse(self):
       while self.getDefinition() is not None:
           pass           
vm=Virtmem(elffile,fl)
fl.close()
#https://www.linuxjournal.com/files/linuxjournal.com/linuxjournal/articles/068/6826/6826l1.html
tsts="""
struct BIGNUM
         {
         uint64 *d|!0|;  
         int top|>0|;     
         int dmax|>0|;  
        int neg;     
         int flags;
        } 

struct key
{
int a,b;
RSA* rs;
}
struct identity {
	identity* next;
    identity** pnext;
	void *key |!0|;
    key r;
	char *comment|text|;
	char *provider|text|;
	uint death;
	uint confirm;
} 
"""
newvar="""
struct BIGNUM
         {
         uint64 *d|!0|;  
         int top|>0|;     
         int dmax|>0|;  
        int neg;     
         int flags;
        } 
        
struct RSA {
    int pad;
    int64 version;
    void *meth;
    void *engine;
    BIGNUM *n;
    BIGNUM *e;
    BIGNUM *d;
    BIGNUM *p;
    BIGNUM *q;
    BIGNUM *dmp1;
    BIGNUM *dmq1;
    BIGNUM *iqmp;
    }
    
struct DSA {
    int pad;
    int32 version;
    BIGNUM *p;
    BIGNUM *q;                 
    BIGNUM *g;
    BIGNUM *pub_key;           
    BIGNUM *priv_key;          
    int flags;
}
        
struct EC_KEY {
    void *meth;
    void *engine;
    int version;
    void *group;
    void *pub_key;
    BIGNUM *priv_key;
    uint enc_flag;

}

struct sshkey {
	int	 type;
	int	 flags;
	RSA	*rsa;
	DSA	*dsa;
	int	 ecdsa_nid;	
	EC_KEY	*ecdsa;
	uchar	*ed25519_sk;
	uchar	*ed25519_pk;

}
 struct identity {
	identity *next;
    identity **pnext;
	sshkey *key|!0|;
	char *comment|text|;
	char *provider|text|;
	int death;
	uint confirm;
} 
struct idtable {
	int nentries|>0|;
    identity *first|!0|; 
    identity **last;
}

"""


#print(ins.validate(vm))
#older signature matching?

newp=stParser(newvar)
newp.parse()
    
#sys.exit(0)    
"""
for sg in vm.segms:
    if sg.data is None: continue
    if(len(sg.data)<4096): continue
    tbl=stInstance(pars.structs['idtable'])
    for ptr in range(sg.virtMem,sg.virtMem+sg.sz-50,4):
        if(tbl.validate_ptr(vm,ptr)):
                print(ptr)
                print(tbl.value["nentries"].value)
    #print(sg.data.count(b'/agent.'))
    continue
    if (sg.data.count(b'/agent.')>=1):
        linst=stInstance(pars.structs['identity'])
        print(sg.virtMem)
        sf=sg.data.find(b'/tmp')
        k=struct.unpack("@P",sg.data[sf-24-8:sf-24])
        idt=vm.getIdtable(k[0])
        sg=vm.addrInSegm(idt.first_ptr)
        if sg is None: break
        for ptr in range(sg.virtMem,sg.virtMem+sg.sz-50,4):
            if(linst.validate_ptr(vm,ptr)):
                print(ptr)
                print(linst.value["comment"].value)
                print(vm.readCstr(linst.value["comment"].value))
        linst=stInstance(pars.structs['identity'])
        #  linst.loadFromBytes(sg.data[idt.first_ptr-sg.virtMem:])
        print(idt.first_ptr)
        print(linst.validate_ptr(vm,idt.first_ptr)) 
        #idf=vm.getIdentity(idt.first_ptr)
        #print(idf.key_ptr)
        #print (vm.readCstr(idf.comment))  """
#need 6.6 older version...
oldvar="""
struct BIGNUM
         {
         uint64 *d|!0|;  
         int top|>0|;     
         int dmax|>0|;  
        int neg;     
         int flags;
        } 
        
struct RSA {
    int pad;
    int64 version;
    void *meth;
    void *engine;
    BIGNUM *n;
    BIGNUM *e;
    BIGNUM *d;
    BIGNUM *p;
    BIGNUM *q;
    BIGNUM *dmp1;
    BIGNUM *dmq1;
    BIGNUM *iqmp;
    }
    
struct DSA {
    int pad;
    int32 version;
    BIGNUM *p;
    BIGNUM *q;                 
    BIGNUM *g;
    BIGNUM *pub_key;           
    BIGNUM *priv_key;          
    int flags;
}
        
struct EC_KEY {
    void *meth;
    void *engine;
    int version;
    void *group;
    void *pub_key;
    BIGNUM *priv_key;
    uint enc_flag;

}

struct Key {
	int	 type|<10|;
	int	 flags;
	RSA	*rsa;
	DSA	*dsa;
	int	 ecdsa_nid;	
	EC_KEY	*ecdsa;
	void *cert;
	uchar	*ed25519_sk;
	uchar	*ed25519_pk;
}
struct identity {
	identity *next;
    identity **prev;
	Key *key |!0|;
	char *comment|text|;
	char *provider;
	int death;
	uint confirm;
}

struct idtab {
	int nentries|>=0| |<100|;
    identity * first;
    identity ** last;
}

struct idmatch
{
idtab idtable[3];
}
"""

def loadBN(vm,stbn):
    addr=stbn.d
    mx=stbn.top
    svv=vm.addrInSegm(addr)
    dad=addr-svv.virtMem
    res=[]
    dat=svv.data[dad:dad+mx*8]
    res=list(dat)
    res.reverse()   
    return bytes_to_long(bytes(res)) 
    
def rsaToKey(vm,rsa):
   nn=rsa.deref('n',vm)
   ee=rsa.deref('e',vm)
   dd=rsa.deref('d',vm)
   return RSA.construct((loadBN(vm,nn),loadBN(vm,ee),loadBN(vm,dd)))
def dsaToKey(vm,dsa):
    yy=loadBN(dsa.deref('pub_key'))
    gg=loadBN(dsa.deref('g'))
    pp=loadBN(dsa.deref('p'))
    qq=loadBN(dsa.deref('q'))
    xx=loadBN(dsa.deref('priv_key'))
    return DSA.construct((yy,gg,pp,qq,xx))


oldp=stParser(oldvar)
oldp.parse()

ccnt=0
kadrs=set([])
for sg in vm.segms:
    if sg.data is None: continue
    if(len(sg.data)<2048): continue
    old_ver=stInstance(oldp.structs['idmatch'])
    new_ver=stInstance(newp.structs['idtable'])
    
    for ptr in range(sg.virtMem,sg.virtMem+sg.sz,4):
        foundkeys=[]
        if(old_ver.validate_ptr(vm,ptr)):
            for a in range(3):
                vl="idtable[%d]"%(a,)
                if  old_ver.value[vl].nentries>0 and old_ver.value[vl].first!=0:
                   print("Found potential old agent key {} at {}".format(a,ptr))        
                   cval=old_ver[vl].deref('first',vm)
                   while cval is not None:
                       foundkeys.append( (cval.deref('key',vm),cval.deref('comment',vm),cval.key) )
                       cval=cval.deref('next',vm)
        if(new_ver.validate_ptr(vm,ptr)):                
              if new_ver.nentries>0 and new_ver.first!=0:
                  print("Found potential new agent key  table at {}".format(ptr)) 
                  cval=new_ver.deref('first',vm)
                  while cval is not None:
                       foundkeys.append((cval.deref('key',vm),cval.deref('comment',vm),cval.key))
                       cval=cval.deref('next',vm)
        if len(foundkeys)>0:
            print("{} potential keys detected".format(len(foundkeys)) )
            for key,comment,kaddr in foundkeys:
                if kaddr in kadrs: continue
                if key is None:continue
                if comment is None:
                    capp=''
                else:
                    capp='_'+comment
                rsa=key.deref('rsa',vm)
                dsa=key.deref('dsa',vm)    
                kadrs.add(kaddr)              
                if rsa is not None:
                    try:
                        k=rsaToKey(vm,rsa)
                        kdat=k.exportKey('PEM')
                        fname="rsa_{}{}".format(ccnt,slugify(capp))
                        fl=open(fname,'wb')
                        fl.write(kdat)
                        fl.close()
                        ccnt+=1
                        print("Wrote out {}".format(fname))
                    except Exception as e:
                        print(e)
                        pass    
                if dsa is not None:
                    try:
                        k=dsaToKey(vm,rsa)
                        kdat=k.exportKey('PEM')
                        fname="dsa_{}{}".format(ccnt,slugify(capp))
                        fl=open(fname,'wb')
                        fl.write(kdat)
                        fl.close()
                        ccnt+=1
                        print("Wrote out {}".format(fname))
                    except:
                        pass                 


