"""GX texture extraction into native RGBA pixels, no image retouching.

Format behavior checked against Dolphin TextureDecoder_Generic.cpp and
TextureDecoder_Util.h (Dolphin Project, GPL-2.0-or-later). This independent
vectorized implementation supports direct and paletted GX formats. Adapted from the reviewed Wario tool.
CMPR uses GX 5:3 interpolation and averaged RGB for transparent selector 3.
"""
import numpy as np
from PIL import Image
BLOCKS={0:(8,8,32),1:(8,4,32),2:(8,4,32),3:(4,4,32),4:(4,4,32),5:(4,4,32),6:(4,4,64),8:(8,8,32),9:(8,4,32),10:(4,4,32),14:(8,8,32)}


def expand(v,bits):
    if bits==3:return (v<<5)|(v<<2)|(v>>1)
    if bits==4:return v*17
    if bits==5:return (v<<3)|(v>>2)
    if bits==6:return (v<<2)|(v>>4)
    raise ValueError(bits)


def rgb565(v):
    return np.stack([expand((v>>11)&31,5),expand((v>>5)&63,6),expand(v&31,5),np.full_like(v,255)],axis=-1)


def decode(data,w,h,fmt,palette=None):
    bw,bh,bs=BLOCKS[fmt];nx=(w+bw-1)//bw;ny=(h+bh-1)//bh
    assert len(data)==nx*ny*bs
    b=np.frombuffer(data,dtype=np.uint8).astype(np.uint32).reshape(-1,bs)
    if fmt==14:
        sub=b.reshape(-1,4,8)
        a=(sub[:,:,0]<<8)|sub[:,:,1];z=(sub[:,:,2]<<8)|sub[:,:,3]
        ca=rgb565(a);cz=rgb565(z)
        mid=(ca+cz)//2;transparent=mid.copy();transparent[:,:,3]=0
        c2=np.where((a>z)[:,:,None],(5*ca+3*cz)>>3,mid)
        c3=np.where((a>z)[:,:,None],(3*ca+5*cz)>>3,transparent)
        colors=np.stack([ca,cz,c2,c3],axis=2)
        selectors=(sub[:,:,4:,None]>>np.array([6,4,2,0]))&3
        tiles=colors[np.arange(len(b))[:,None,None,None],np.arange(4)[None,:,None,None],selectors]
        tiles=tiles.reshape(-1,2,2,4,4,4).transpose(0,1,3,2,4,5).reshape(-1,8,8,4)
    else:
        if fmt==0:
            v=np.stack([b>>4,b&15],axis=-1).reshape(-1,64)*17
            rgba=np.repeat(v[:,:,None],4,axis=2)
        elif fmt==1:rgba=np.repeat(b[:,:,None],4,axis=2)
        elif fmt==2:
            v=(b&15)*17;rgba=np.stack([v,v,v,(b>>4)*17],axis=-1)
        elif fmt==3:
            alpha=b[:,0::2];v=b[:,1::2];rgba=np.stack([v,v,v,alpha],axis=-1)
        elif fmt==4:rgba=rgb565((b[:,0::2]<<8)|b[:,1::2])
        elif fmt in (8,9,10):
            if palette is None:raise ValueError('Missing palette')
            if fmt==8:indices=np.stack([b>>4,b&15],axis=-1).reshape(-1,64)
            elif fmt==9:indices=b
            else:indices=((b[:,0::2]<<8)|b[:,1::2])&0x3fff
            rgba=np.asarray(palette,dtype=np.uint32)[indices]
        elif fmt==5:
            v=(b[:,0::2]<<8)|b[:,1::2];opaque=(v&0x8000)!=0
            rgba=np.stack([np.where(opaque,expand((v>>10)&31,5),expand((v>>8)&15,4)),
                           np.where(opaque,expand((v>>5)&31,5),expand((v>>4)&15,4)),
                           np.where(opaque,expand(v&31,5),expand(v&15,4)),
                           np.where(opaque,255,expand((v>>12)&7,3))],axis=-1)
        elif fmt==6:rgba=np.stack([b[:,1:32:2],b[:,32::2],b[:,33::2],b[:,:32:2]],axis=-1)
        else:raise ValueError(f'Unsupported palette/texture format: {fmt}')
        tiles=rgba.reshape(-1,bh,bw,4)
    pixels=tiles.reshape(ny,nx,bh,bw,4).transpose(0,2,1,3,4).reshape(ny*bh,nx*bw,4)
    return Image.fromarray(pixels[:h,:w].astype(np.uint8))


def palette_rgba(data,fmt):
    v=np.frombuffer(data,dtype='>u2').astype(np.uint32)
    if fmt==0:
        i=v&255
        return np.stack([i,i,i,v>>8],axis=-1)
    if fmt==1:return rgb565(v)
    if fmt==2:
        return np.stack([np.where(v&0x8000,expand((v>>10)&31,5),expand((v>>8)&15,4)),
            np.where(v&0x8000,expand((v>>5)&31,5),expand((v>>4)&15,4)),
            np.where(v&0x8000,expand(v&31,5),expand(v&15,4)),
            np.where(v&0x8000,255,expand((v>>12)&7,3))],axis=-1)
    raise ValueError('Unknown palette format')


def size(w,h,fmt):
    bw,bh,bs=BLOCKS[fmt]
    return ((w+bw-1)//bw)*((h+bh-1)//bh)*bs


def self_test():
    assert decode(bytes.fromhex('07e0')*16,4,4,4).getpixel((0,0))==(0,255,0,255)
    pal=palette_rgba(bytes.fromhex('8000ffff'),2)
    assert decode(bytes([1])*32,8,8,8,pal).getpixel((1,0))==(255,255,255,255)
    assert tuple(palette_rgba(bytes.fromhex('2a64'),0)[0])==(100,100,100,42)
    assert decode(bytes([0x1f])*32,8,8,0).getpixel((0,0))==(17,17,17,17)
    assert decode(bytes([0x1f])*32,8,8,0).getpixel((1,0))==(255,)*4
    assert decode(bytes([37])*32,8,4,1).getpixel((0,0))==(37,)*4
    assert decode(bytes([0xa3])*32,8,4,2).getpixel((0,0))==(51,51,51,170)
    assert decode(bytes([42,100])*16,4,4,3).getpixel((0,0))==(100,100,100,42)
    assert decode(bytes.fromhex('fc00')*16,4,4,5).getpixel((0,0))==(255,0,0,255)
    assert decode(bytes.fromhex('1f00')*16,4,4,5).getpixel((0,0))==(255,0,0,36)
    assert decode(bytes([50,60])*16+bytes([70,80])*16,4,4,6).getpixel((0,0))==(60,70,80,50)
    block=bytes.fromhex('f80007e01b1b1b1b')
    cmpr=decode(block*4,8,8,14)
    assert [cmpr.getpixel((i,0)) for i in range(4)]==[(255,0,0,255),(0,255,0,255),(159,95,0,255),(95,159,0,255)]
    assert decode(bytes.fromhex('0000ffffffffffFF')*4,8,8,14).getpixel((0,0))==(127,127,127,0)
    assert decode(bytes([0])*128,9,9,0).size==(9,9)
    print('GX channel, alpha, tile/crop and CMPR selector fixtures passed.')


if __name__=='__main__':self_test()
