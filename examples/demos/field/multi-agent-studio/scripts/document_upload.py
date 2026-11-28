# SPDX-License-Identifier: Apache-2.0

"""Bounded document decoding; PDF extraction uses the host's Poppler tools."""
import base64
import binascii
from pathlib import Path
import shutil
import subprocess
import tempfile
import io
import posixpath
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET

MAX_FILE = 10 * 1024 * 1024
MAX_TEXT = MAX_FILE
MAX_PAGES = 100


def decode_document(name, data):
    suffix = Path(name).suffix.lower()
    if suffix not in ('.txt', '.md', '.csv', '.pdf', '.pptx', '.xlsx'):
        raise ValueError('Upload a PDF, PPTX, XLSX, CSV, Markdown or text document. Convert older .ppt files to .pptx or PDF first.')
    if suffix not in ('.pdf', '.pptx', '.xlsx'):
        content = data.get('content')
        if not isinstance(content, str) or not content.strip() or '\x00' in content:
            raise ValueError('This document has no readable text. Save CSV and text files as UTF-8.')
        content = content.removeprefix('\ufeff')
        if len(content.encode('utf-8')) > MAX_TEXT:
            raise ValueError('Choose a document of 10 MB or smaller.')
        return content.encode('utf-8'), None
    if data.get('encoding') != 'base64' or not isinstance(data.get('content'), str):
        raise ValueError('Upload the PDF, PPTX or XLSX as a binary document.')
    try:
        raw = base64.b64decode(data['content'], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('The document upload is invalid.') from None
    if suffix=='.xlsx':
        if not raw or len(raw)>MAX_FILE:
            raise ValueError('Choose an XLSX of 10 MB or smaller.')
        return raw, xlsx_text(name, raw)
    if suffix=='.pptx':
        if not raw or len(raw)>MAX_FILE:
            raise ValueError('Choose a PPTX of 10 MB or smaller.')
        return raw, pptx_text(name, raw)
    if not raw or len(raw) > MAX_FILE or not raw.startswith(b'%PDF-'):
        raise ValueError('Choose a valid PDF of 10 MB or smaller.')
    if not shutil.which('pdftotext') or not shutil.which('pdfinfo'):
        raise ValueError('PDF support needs Poppler on the host: Ubuntu: sudo apt-get install poppler-utils; macOS: brew install poppler.')
    with tempfile.TemporaryDirectory(prefix='bac-pdf-') as directory:
        source = Path(directory) / 'document.pdf'
        output = Path(directory) / 'document.txt'
        source.write_bytes(raw)
        try:
            info = subprocess.run(['pdfinfo', str(source)], capture_output=True, text=True, timeout=10)
            if info.returncode:
                raise ValueError('This PDF is damaged or password-protected. Upload an unlocked copy.')
            fields = dict(line.split(':', 1) for line in info.stdout.splitlines() if ':' in line)
            pages = int(fields.get('Pages', '0').strip())
            if not 0 < pages <= MAX_PAGES:
                raise ValueError('Upload a PDF with 1–100 pages; split longer documents first.')
            result = subprocess.run(['pdftotext', '-layout', '-enc', 'UTF-8', str(source), str(output)], capture_output=True, timeout=20)
            if result.returncode or not output.exists():
                raise ValueError('Text could not be extracted from this PDF. Try an unlocked, text-based copy.')
            if output.stat().st_size > MAX_TEXT:
                raise ValueError('The PDF contains too much text. Split it into smaller documents.')
            extracted = output.read_text(encoding='utf-8')
        except subprocess.TimeoutExpired:
            raise ValueError('PDF processing timed out. Try a smaller document.') from None
    if not extracted.strip():
        raise ValueError('This PDF has no extractable text. It may be a scan; run OCR or upload a text-based PDF.')
    sections = extracted.split('\f')
    if sections and not sections[-1].strip():
        sections.pop()
    readable = 'Source: '+name+'\nPDF text extraction; visual layout and images may be omitted.\n\n'
    readable += '\n\n'.join('--- Page %d ---\n%s' % (i, page.strip() or '[No text extracted on this page; an image or scan may need OCR.]') for i,page in enumerate(sections,1))
    if len(readable.encode('utf-8')) > MAX_TEXT:
        raise ValueError('The PDF contains too much text. Split it into smaller documents.')
    return raw, readable


def xlsx_text(name, raw):
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
        'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if len(entries)>5000 or sum(f.file_size for f in entries)>100*1024*1024:
                raise ValueError('This workbook is too large after unpacking.')
            def xml(path):
                if archive.getinfo(path).file_size>20*1024*1024:
                    raise ValueError('A workbook sheet contains too much data.')
                content=archive.read(path)
                if b'<!DOCTYPE' in content or b'<!ENTITY' in content:
                    raise ValueError('Unsupported workbook XML.')
                return ET.fromstring(content)
            relations={r.attrib['Id']:r.attrib['Target'] for r in xml('xl/_rels/workbook.xml.rels') if r.attrib.get('TargetMode')!='External'}
            shared=[]
            if 'xl/sharedStrings.xml' in archive.namelist():
                shared=[''.join(t.text or '' for t in item.findall('.//s:t',ns)) for item in xml('xl/sharedStrings.xml')]
            sheets=xml('xl/workbook.xml').findall('s:sheets/s:sheet',ns)
            if not 0<len(sheets)<=100:
                raise ValueError('Upload a workbook with 1–100 sheets.')
            lines=[];size=0;cells=0
            def emit(line):
                nonlocal size
                size+=len(line.encode('utf-8'))+1
                if size>MAX_TEXT:raise ValueError('This workbook contains too much text. Split it first.')
                lines.append(line)
            emit('Source: '+name)
            emit('Sheet cell extraction. Formatting, charts and images are omitted. Dates may be Excel serial numbers. Formulas are not recalculated; cached results may be outdated.')
            for sheet in sheets:
                target=relations[sheet.attrib['{'+ns['r']+'}id']]
                path=posixpath.normpath('xl/'+target) if not target.startswith('/') else target.lstrip('/')
                if not path.startswith('xl/worksheets/'):
                    raise ValueError('Invalid worksheet reference.')
                emit('\n--- Sheet: '+sheet.attrib['name']+' ---')
                for cell in xml(path).findall('.//s:sheetData/s:row/s:c',ns):
                    value=cell.findtext('s:v',default='',namespaces=ns)
                    kind=cell.attrib.get('t')
                    if kind=='s':
                        index=int(value)
                        if index<0 or index>=len(shared):raise ValueError('Invalid shared string reference.')
                        value=shared[index]
                    elif kind=='inlineStr':value=''.join(t.text or '' for t in cell.findall('.//s:t',ns))
                    elif kind=='b':value='TRUE' if value=='1' else 'FALSE'
                    formula=cell.find('s:f',ns)
                    if formula is not None:
                        value='[Formula: '+(formula.text or 'shared formula')+'; cached result: '+(value or 'unavailable')+']'
                    if value:
                        cells+=1
                        if cells>100000:raise ValueError('This workbook has too many cells. Split it first.')
                        emit(cell.attrib.get('r','Cell')+': '+value)
            if not cells:raise ValueError('This workbook has no readable cells.')
            return '\n'.join(lines)
    except (BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError):
        raise ValueError('This XLSX is damaged, encrypted or unsupported. Upload an unlocked XLSX or CSV.') from None


def pptx_text(name, raw):
    ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main', 'a':'http://schemas.openxmlformats.org/drawingml/2006/main', 'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist())>5000 or sum(f.file_size for f in archive.infolist())>100*1024*1024:
                raise ValueError('This presentation is too large after unpacking.')
            def xml(path):
                if archive.getinfo(path).file_size>5*1024*1024:
                    raise ValueError('A slide contains too much data.')
                content=archive.read(path)
                if b'<!DOCTYPE' in content or b'<!ENTITY' in content:
                    raise ValueError('Unsupported presentation XML.')
                return ET.fromstring(content)
            relations={r.attrib['Id']:r.attrib['Target'] for r in xml('ppt/_rels/presentation.xml.rels') if r.attrib.get('TargetMode')!='External'}
            slides=xml('ppt/presentation.xml').findall('p:sldIdLst/p:sldId',ns)
            if not 0<len(slides)<=MAX_PAGES:
                raise ValueError('Upload a presentation with 1–100 slides.')
            sections=[]
            for index,slide in enumerate(slides,1):
                target=relations[slide.attrib['{'+ns['r']+'}id']]
                path=posixpath.normpath('ppt/'+target) if not target.startswith('/') else target.lstrip('/')
                if not path.startswith('ppt/slides/'):
                    raise ValueError('Invalid slide reference.')
                root=xml(path)
                lines=[''.join(t.text or '' for t in paragraph.findall('.//a:t',ns)) for paragraph in root.findall('.//a:p',ns)]
                sections.append('--- Slide %d ---\n%s' % (index,'\n'.join(lines).strip() or '[No slide text; images may need visual review.]'))
            output='Source: '+name+'\nSlide text extraction; images, charts and speaker notes are not included.\n\n'+'\n\n'.join(sections)
            if len(output.encode('utf-8'))>MAX_TEXT:
                raise ValueError('This presentation contains too much text. Split it first.')
            if not any(root for root in sections if '[No slide text;' not in root):
                raise ValueError('This presentation has no slide text. Export slides as images for a vision model.')
            return output
    except (BadZipFile,KeyError,ET.ParseError,RuntimeError,OSError):
        raise ValueError('This PPTX is damaged, encrypted or unsupported. Export an unlocked PPTX or PDF.') from None
