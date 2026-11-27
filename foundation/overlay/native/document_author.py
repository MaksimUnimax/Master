"""Bounded structured document authoring for the Harness chat worker.

No executable model code, user paths, external resources, or network. Office
intermediates use ODF and the installed Harness LibreOffice Kit performs conversion.
"""
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from xml.etree import ElementTree as E

sys.path.insert(0,str(Path(__file__).resolve().parent))
FORMATS={"xlsx","docx","pptx","pdf","csv","txt","json","zip"}
MAX_SPEC=256*1024
MAX_BYTES=8*1024*1024
NS={
 "office":"urn:oasis:names:tc:opendocument:xmlns:office:1.0",
 "text":"urn:oasis:names:tc:opendocument:xmlns:text:1.0",
 "style":"urn:oasis:names:tc:opendocument:xmlns:style:1.0",
 "fo":"urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
 "table":"urn:oasis:names:tc:opendocument:xmlns:table:1.0",
 "draw":"urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
 "svg":"urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
 "presentation":"urn:oasis:names:tc:opendocument:xmlns:presentation:1.0",
 "manifest":"urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
}
for prefix,uri in NS.items():E.register_namespace(prefix,uri)

def q(k):
 p,n=k.split(":",1);return "{"+NS[p]+"}"+n
def attrs(d):return {q(k):str(v) for k,v in d.items()}
def element(parent,tag,attributes=None,text=None):
 item=E.Element(q(tag),attrs(attributes or {})) if parent is None else E.SubElement(parent,q(tag),attrs(attributes or {}))
 if text is not None:item.text=text
 return item
def xml(el):return E.tostring(el,encoding="utf-8",xml_declaration=True)

def require(condition,message="Некорректная структура документа."):
 if not condition:raise ValueError(message)

def plain(value,maxlen=16000,empty=True):
 require(isinstance(value,str) and len(value)<=maxlen and (empty or value.strip()),"Некорректный текст документа.")
 require(not any(ord(c)<32 and c not in "\n\r\t" or 0xd800<=ord(c)<=0xdfff or ord(c) in (0xfffe,0xffff) for c in value),"Недопустимый символ документа.")
 return value

def obj(value,allowed,required=()):
 require(isinstance(value,dict) and set(value)<=set(allowed) and set(required)<=set(value))
 return value

def array(value,limit,nonempty=False):
 require(isinstance(value,list) and len(value)<=limit and (not nonempty or len(value)>0))
 return value

def scalar(value):
 if value is None or type(value) is bool:return value
 if type(value) in (int,float):
  require(math.isfinite(value) and abs(value)<=1e15,"Недопустимое число.")
  return value
 return plain(value,8000)

def formula(value):
 require(isinstance(value,dict) and set(value)=={"formula"})
 f=plain(value["formula"],250,False)
 # Only arithmetic, cell references, simple vetted functions; no external refs,
 # links, strings, volatile services, DDE or cross-workbook/sheet expressions.
 require(f.startswith("=") and re.fullmatch(r"=[A-Za-z0-9_.$+\-*/^%(),: <>=]+",f),"Недопустимая формула.")
 fn=re.findall(r"([A-Za-z_][A-Za-z_0-9.]*)\s*\(",f)
 require(all(x.upper() in {"SUM","AVERAGE","MIN","MAX","COUNT","COUNTA","IF","ROUND","ROUNDUP","ROUNDDOWN","ABS","AND","OR","NOT","SUMIF","COUNTIF","IFERROR","PRODUCT","INT","MOD"} for x in fn),"Функция формулы недоступна.")
 residue=re.sub(r"[A-Za-z_][A-Za-z_0-9.]*\s*\(","(",f)
 residue=re.sub(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}","0",residue)
 require(not re.search(r"[A-Za-z_]",residue),"Недопустимая ссылка в формуле.")
 return f

def rows(value,formulas=False):
 out=[]
 for row in array(value,2000,True):
  require(isinstance(row,list) and 0<len(row)<=40)
  out.append([formula(v) if formulas and isinstance(v,dict) else scalar(v) for v in row])
 require(sum(map(len,out))<=30000)
 return out

def name_for(name,fmt):
 require(fmt in FORMATS and isinstance(name,str))
 require(0<len(name)<=160 and name==name.strip() and name not in (".","..") and not re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]',name),"Недопустимое имя файла.")
 require(not name.startswith("."),"Недопустимое имя файла.")
 suffix=Path(name).suffix.lower()
 if suffix:
  require(suffix=="."+fmt,"Расширение не соответствует формату.")
  return name
 return name+"."+fmt

def cell_text(v):
 if v is None:return ""
 if type(v) is bool:return "Да" if v else "Нет"
 return str(v)

def write_xlsx(spec):
 from openpyxl import Workbook
 from openpyxl.styles import Font,PatternFill,Alignment
 from openpyxl.utils import get_column_letter
 obj(spec,{"sheets"},{"sheets"})
 wb=Workbook();wb.remove(wb.active);total=0;seen=set()
 for sh in array(spec["sheets"],24,True):
  obj(sh,{"name","rows","header"},{"name","rows"})
  title=plain(sh["name"],31,False)
  require(not re.search(r"[\[\]:*?/\\]",title) and title.casefold() not in seen,"Некорректное имя листа.")
  seen.add(title.casefold());sheet=wb.create_sheet(title)
  vals=rows(sh["rows"],True);total+=sum(map(len,vals));require(total<=40000,"Слишком много ячеек.")
  header=sh.get("header",True);require(type(header) is bool)
  for i,row in enumerate(vals,1):
   for j,v in enumerate(row,1):
    c=sheet.cell(i,j,v)
    original=sh["rows"][i-1][j-1]
    if isinstance(v,str) and not isinstance(original,dict):c.data_type="s"
    if i==1 and header:
     c.font=Font(name="Calibri",bold=True,color="FFFFFF");c.fill=PatternFill("solid",fgColor="25634D")
    c.alignment=Alignment(vertical="top",wrap_text=True)
  for j in range(1,sheet.max_column+1):
   width=max([len(cell_text(r[j-1])) for r in vals[:300] if j<=len(r)]+[8])
   sheet.column_dimensions[get_column_letter(j)].width=min(48,max(12,width+2))
  if header:sheet.freeze_panes="A2";sheet.auto_filter.ref=sheet.dimensions
 out=io.BytesIO();wb.save(out);return out.getvalue()

def odf_base(mime):
 content=element(None,"office:document-content",{"office:version":"1.2"})
 automatic=element(content,"office:automatic-styles")
 body=element(content,"office:body")
 styles=element(None,"office:document-styles",{"office:version":"1.2"})
 common=element(styles,"office:styles")
 automatic_styles=element(styles,"office:automatic-styles")
 masters=element(styles,"office:master-styles")
 return content,automatic,body,styles,common,automatic_styles,masters

def para_style(parent,name,size,bold=False,color="#22342B",bottom="0.12in",**kw):
 st=element(parent,"style:style",{"style:name":name,"style:family":"paragraph"})
 element(st,"style:paragraph-properties",{"fo:margin-bottom":bottom,**kw})
 element(st,"style:text-properties",{"fo:font-family":"DejaVu Sans","fo:font-size":size,"fo:color":color,**({"fo:font-weight":"bold"} if bold else {})})
 return st

def add_paragraph(parent,value,style="Body",heading=None):
 value=plain(value)
 if heading:node=element(parent,"text:h",{"text:style-name":style,"text:outline-level":heading})
 else:node=element(parent,"text:p",{"text:style-name":style})
 # ODF whitespace controls preserve line breaks and repeated spaces.
 for i,line in enumerate(value.split("\n")):
  if i:element(node,"text:line-break")
  if len(node):node[-1].tail=(node[-1].tail or "")+line
  else:node.text=(node.text or "")+line
 return node

def page_layout(auto,masters,w,h,margin="0.65in"):
 layout=element(auto,"style:page-layout",{"style:name":"PMPage"})
 element(layout,"style:page-layout-properties",{"fo:page-width":w,"fo:page-height":h,"fo:margin":margin,"style:print-orientation":"landscape" if w=="13.333in" else "portrait"})
 element(masters,"style:master-page",{"style:name":"Standard","style:page-layout-name":"PMPage"})

def odf_zip(mime,content,styles):
 manifest=element(None,"manifest:manifest",{"manifest:version":"1.2"})
 for n,t in (("/",mime),("content.xml","text/xml"),("styles.xml","text/xml")):
  element(manifest,"manifest:file-entry",{"manifest:full-path":n,"manifest:media-type":t})
 out=io.BytesIO()
 with ZipFile(out,"w",compression=ZIP_DEFLATED) as z:
  z.writestr("mimetype",mime,compress_type=ZIP_STORED)
  z.writestr("content.xml",xml(content));z.writestr("styles.xml",xml(styles));z.writestr("META-INF/manifest.xml",xml(manifest))
 return out.getvalue()

def write_odt(spec):
 obj(spec,{"title","sections"},{"title","sections"})
 mime="application/vnd.oasis.opendocument.text"
 content,auto,body,styles,common,stylesauto,masters=odf_base(mime)
 page_layout(stylesauto,masters,"8.27in","11.69in")
 para_style(common,"Title","23pt",True,"#25634D","0.20in")
 para_style(common,"Heading","15pt",True,"#25634D","0.12in",**{"fo:keep-with-next":"always"})
 para_style(common,"Body","11pt",False,"#22342B","0.12in")
 para_style(common,"TableHead","10pt",True,"#FFFFFF","0in")
 para_style(common,"TableBody","9pt",False,"#22342B","0in")
 for nm,col in (("HeaderCell","#25634D"),("NormalCell","#FFFFFF")):
  st=element(auto,"style:style",{"style:name":nm,"style:family":"table-cell"})
  element(st,"style:table-cell-properties",{"fo:background-color":col,"fo:border":"0.5pt solid #D2DED6","fo:padding":"0.06in"})
 text=element(body,"office:text")
 add_paragraph(text,plain(spec["title"],300,False),"Title",1)
 for i,section in enumerate(array(spec["sections"],100,True)):
  obj(section,{"heading","paragraphs","table"})
  if section.get("heading"):add_paragraph(text,plain(section["heading"],300),"Heading",2)
  for p in array(section.get("paragraphs",[]),300):add_paragraph(text,p)
  if "table" in section:
   t=obj(section["table"],{"headers","rows"},{"headers","rows"})
   heads=array(t["headers"],10,True);heads=[plain(x,300) for x in heads]
   rr=rows(t["rows"]);require(all(len(x)==len(heads) for x in rr),"Строки таблицы не совпадают с заголовками.")
   tab=element(text,"table:table",{"table:name":"Table"+str(i+1)})
   colstyle="Col"+str(i+1)
   st=element(auto,"style:style",{"style:name":colstyle,"style:family":"table-column"})
   element(st,"style:table-column-properties",{"style:column-width":str(round(6.9/len(heads),3))+"in"})
   for _ in heads:element(tab,"table:table-column",{"table:style-name":colstyle})
   header=element(tab,"table:table-header-rows")
   for j,row in enumerate([heads]+rr):
    tr=element(header if j==0 else tab,"table:table-row")
    for v in row:
     cell=element(tr,"table:table-cell",{"office:value-type":"string","table:style-name":"HeaderCell" if j==0 else "NormalCell"})
     add_paragraph(cell,cell_text(v),"TableHead" if j==0 else "TableBody")
 return odf_zip(mime,content,styles)

def write_odp(spec):
 obj(spec,{"title","slides"},{"title","slides"})
 mime="application/vnd.oasis.opendocument.presentation"
 content,auto,body,styles,common,stylesauto,masters=odf_base(mime)
 page_layout(stylesauto,masters,"13.333in","7.5in","0in")
 para_style(common,"SlideTitle","28pt",True,"#25634D","0.15in")
 para_style(common,"SlideBody","19pt",False,"#22342B","0.20in")
 para_style(common,"SlideSubtitle","15pt",False,"#65796B","0.10in")
 st=element(auto,"style:style",{"style:name":"PMFrame","style:family":"graphic"})
 element(st,"style:graphic-properties",{"draw:fill":"none","draw:stroke":"none","fo:padding":"0in"})
 doc=element(body,"office:presentation")
 title=plain(spec["title"],120,False)
 for i,slide in enumerate(array(spec["slides"],40,True)):
  obj(slide,{"title","bullets","subtitle"},{"title","bullets"})
  heading=plain(slide["title"],110,False)
  bullets=[plain(x,180,False) for x in array(slide["bullets"],7)]
  require(sum(len(x) for x in bullets)<=740,"Слишком много текста на одном слайде.")
  page=element(doc,"draw:page",{"draw:name":"Слайд "+str(i+1),"draw:master-page-name":"Standard"})
  def frame(x,y,w,h):
   fr=element(page,"draw:frame",{"draw:style-name":"PMFrame","svg:x":x,"svg:y":y,"svg:width":w,"svg:height":h})
   return element(fr,"draw:text-box")
  add_paragraph(frame("0.65in","0.40in","12in","1.1in"),heading,"SlideTitle")
  text=frame("0.72in","1.68in","11.9in","5.05in")
  for item in bullets:add_paragraph(text,"• "+item,"SlideBody")
  footer=plain(slide.get("subtitle",title),140)
  add_paragraph(frame("0.72in","6.96in","11.9in","0.38in"),footer+"  ·  "+str(i+1),"SlideSubtitle")
 return odf_zip(mime,content,styles)

def render(fmt,spec):
 require(fmt in FORMATS)
 if fmt=="xlsx":return "xlsx",write_xlsx(spec)
 if fmt in ("docx","pdf"):return "odt",write_odt(spec)
 if fmt=="pptx":return "odp",write_odp(spec)
 if fmt=="txt":
  obj(spec,{"text"},{"text"});return fmt,plain(spec["text"],MAX_SPEC).encode("utf-8")
 if fmt=="json":
  obj(spec,{"data"},{"data"});return fmt,(json.dumps(spec["data"],ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode()
 if fmt=="csv":
  obj(spec,{"rows","delimiter"},{"rows"})
  delimiter=spec.get("delimiter",";");require(delimiter in (";",",","\t"))
  out=io.StringIO(newline="");writer=csv.writer(out,delimiter=delimiter)
  for row in rows(spec["rows"]):
   writer.writerow(["'"+v if isinstance(v,str) and v[:1] in ("=","+","-","@","\t","\r") else cell_text(v) for v in row])
  return fmt,("\ufeff"+out.getvalue()).encode("utf-8")
 # ZIP is assembled by the native host from scoped, validated document receipts.
 raise ValueError("Архив формируется из файлов текущего диалога.")

def main():
 from file_isolation import filesystem
 from file_worker import confine
 with tempfile.TemporaryDirectory(prefix="pm-author-") as temp:
  parent=os.getpid();pid=os.fork()
  if pid==0:
   try:
    import ctypes
    ctypes.CDLL(None).prctl(1,9,0,0,0)
    if os.getppid()!=parent:os._exit(2)
    os.chdir(temp);os.environ.update(HOME=temp,TMPDIR=temp);tempfile.tempdir=temp
    filesystem(temp);confine()
    raw=sys.stdin.buffer.read(MAX_SPEC+1)
    require(len(raw)<=MAX_SPEC,"Слишком большой документ.")
    fmt,spec=json.loads(raw)
    actual,data=render(fmt,spec)
    require(0<len(data)<=MAX_BYTES,"Файл превышает 8 МиБ или пуст.")
    import base64
    print(json.dumps({"format":actual,"body":base64.b64encode(data).decode("ascii")},ensure_ascii=False),flush=True)
    os._exit(0)
   except Exception as exc:
    message=str(exc) if isinstance(exc,ValueError) and re.match(r"[А-Яа-я]",str(exc)) else "Не удалось сформировать документ."
    print(json.dumps({"error":message},ensure_ascii=False),flush=True);os._exit(0)
  _,status=os.waitpid(pid,0)
  sys.exit(os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 2)

if __name__=="__main__":main()
