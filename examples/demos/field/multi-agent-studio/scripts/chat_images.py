# SPDX-License-Identifier: Apache-2.0

"""Inline chat image validation. Never fetch user-supplied remote URLs."""
import base64
import binascii

MAX_IMAGES = 4
MAX_BYTES = 2 * 1024 * 1024


def validate_images(images):
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ValueError('Attach up to four images per message.')
    result=[]
    for item in images:
        if not isinstance(item,dict):
            raise ValueError('Invalid image attachment.')
        url=item.get('dataUrl','')
        if not isinstance(url,str) or len(url)>MAX_BYTES*4//3+100:
            raise ValueError('Each image must be 2 MB or smaller.')
        header,separator,data=url.partition(',')
        mime=header.removeprefix('data:').removesuffix(';base64')
        if not separator or header!='data:'+mime+';base64' or mime not in ('image/png','image/jpeg','image/webp'):
            raise ValueError('Use PNG, JPEG or WebP images.')
        try:raw=base64.b64decode(data,validate=True)
        except (ValueError,binascii.Error):raise ValueError('Invalid image data.') from None
        valid=(mime=='image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n') or mime=='image/jpeg' and raw.startswith(b'\xff\xd8\xff') or mime=='image/webp' and raw.startswith(b'RIFF') and raw[8:12]==b'WEBP')
        if not valid or not raw or len(raw)>MAX_BYTES:
            raise ValueError('Invalid or oversized image attachment.')
        result.append((mime,raw))
    return result
