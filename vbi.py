#!/usr/bin/env python

# * Copyright 2011 Alistair Buxton <a.j.buxton@gmail.com>
# *
# * License: This program is free software; you can redistribute it and/or
# * modify it under the terms of the GNU General Public License as published
# * by the Free Software Foundation; either version 3 of the License, or (at
# * your option) any later version. This program is distributed in the hope
# * that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# * warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# * GNU General Public License for more details.

# This is the main data analyser.

import sys

import numpy as np
from scipy.interpolate import interp1d
from scipy.ndimage import gaussian_filter1d as gauss
from scipy.optimize import fminbound

import pylab

from util import paritybytes, setbyte, normalise, hammbytes, allbytes
from printit import do_print

import time

class Vbi(object):
    '''This class represents a line of raw vbi data and all our attempts to
        decode it.'''

    def __init__(self, vbi):

        # data arrays

        # vbi is the raw line as an array of 2048 floats
        self.vbi = vbi

        # black level of the signal
        self.black = np.mean(self.vbi[:80])

        # scale factor of the vbi, calculated later
        self.scale = 0

        # note: guess and mask are 376 "bits" long because an extra "byte" is 
        # needed at the beginning and the end for interpolation to work 
        # correctly. setbyte and bitstobytes take this into account.

        # guess is the best guess at what the vbi contains
        self.guess = np.zeros(47*8, dtype=np.float)
        setbyte(self.guess, -1, 0x0)
        setbyte(self.guess, 0, 0x55)
        setbyte(self.guess, 1, 0x55)
        setbyte(self.guess, 2, 0x27)

        # mask is used to mark regions of interest in the interpolated guess
        self.mask = np.zeros(47*8, dtype=np.float)
        setbyte(self.mask, -1, 0xff)
        setbyte(self.mask, 0, 0xff)
        setbyte(self.mask, 1, 0xff)
        setbyte(self.mask, 2, 0xff)

        # vbi packet bytewise
        self._mask0 = np.zeros(42, dtype=np.uint8)
        self._mask1 = np.zeros(42, dtype=np.uint8)

        # parameters for interpolation
        self._bitwidth = 5.112
        self._offset = 0

        # params for convolve
        self._gauss_sd = 5.5 # TWEAK: amount of gaussian blurring to apply
                             # this cuts out hi freq. noise in the samples
                             # but also reduces the amount of data

        # interpolation objects
        self._interp_x = np.zeros(376, dtype=np.float)
        self._guess_x = np.zeros(2048, dtype=np.float)
        self.set_bitwidth(self._bitwidth)
        self.set_offset(self._offset)

        self.guess_scaler = interp1d(self._interp_x, self.guess, 
                                     kind='linear', copy=False, 
                                     bounds_error=False, fill_value=0)
        # note that mask_scaler uses the same offsets as guess_scaler
        # and has fill value = 1 because we always are interested in the
        # samples outside the signal as they should never change
        self.mask_scaler = interp1d(self._interp_x, self.mask, 
                                     kind='linear', copy=False, 
                                     bounds_error=False, fill_value=1)

    def set_bitwidth(self, bitwidth):
        self._bitwidth = bitwidth
        self._interp_x[:] = (np.arange(0,47*8,1.0) * bitwidth) - bitwidth*8

    def set_offset(self, offset):
        self._offset = offset
        self._guess_x[:] = np.arange(0,2048,1.0) - offset

    def find_offset_and_scale(self):
        '''Tries to find the offset of the vbi data in the raw samples.'''

        # Only consider the general area of the CRI
        target = gauss(self.vbi[64:256], self._gauss_sd)

        def _inner(offset):
            self.set_offset(offset)
            guess_scaled = gauss(self.guess_scaler(self._guess_x[64:256]), self._gauss_sd)
            #mask_scaled = gauss(self.mask_scaler(self._guess_x[64:256]), self._gauss_sd)
            mask_scaled = self.mask_scaler(self._guess_x[64:256]) # not blurring this seems to be better

            a = guess_scaled*mask_scaled
            b = np.clip(target*mask_scaled, self.black, 256)

            self.scale = a.std()/b.std()
            b -= self.black
            b *= self.scale
            a = np.clip(a, 0, 256*self.scale)

            return np.sum(np.square(a-b))

        offset = fminbound(_inner, 96.0, 110.0)

        # call it also to set self.offset and self.scale
        return (_inner(offset) < 5.0)

    def make_guess_mask(self,o=0):
        a = []
        for i in range(42*8):
            a.append([])
        b = 4*8

        gx = self._guess_x + (self._bitwidth*0.5) + o

        for i in range(2048):
            while b < 368 and gx[i] > self._interp_x[b+1]:
                b += 1
            if self._interp_x[b] < gx[i] and b < 368:
                a[b-4*8].append(self.vbi[i])

        mins = np.array([min(x) for x in a])
        maxs = np.array([max(x) for x in a])
        avgs = np.array([np.array(x).mean() for x in a])

        for i in range(42):
            mini = mins[i*8:(i+1)*8]
            maxi = maxs[i*8:(i+1)*8]
            avgi = avgs[i*8:(i+1)*8]
            self._mask0[i] = 0xff
            for j in range(8):
                if mini[j] < self.black+10.0:
                    self._mask0[i] &= ~(1<<j)
                if maxi[j] > self.black*2.5:
                    self._mask1[i] |= (1<<j)

        tmp = self._mask1 & self._mask0
        self._mask0 |= self._mask1
        self._mask1 = tmp


    def possible_bytes(self, n, half=False):
        '''Returns the list of possible values at byte n.'''
        if n == 42 and half:
            return [0]

        if n < 2:
            bytes = hammbytes
        elif n < 5:
            bytes = allbytes
        else:
            bytes = paritybytes

        ans = filter(lambda x: (x&self._mask0[n])==x==(x|self._mask1[n]), bytes)
        if ans == []:
            ans = bytes
        if half:
            ans = list(set([x&0x1f for x in ans]))
        return ans

    def deconvolve(self):
        self.make_guess_mask()

        target = gauss(self.vbi, self._gauss_sd)
        #target -= self.black
        #target *= self.scale
        target = normalise(target)

        self._bytes = np.zeros(42, dtype=np.uint8)
        self._oldbytes = np.zeros(42, dtype=np.uint8)

        nb = self.possible_bytes(0)
        count = 0
        for it in range(10): # TWEAK: maximum number of iterations.
            for n in range(42):                   
                nb = self.possible_bytes(n)
                nnb = self.possible_bytes(n+1, half=True)
                if len(nb) == 1:
                    setbyte(self.guess, n+3, nb[0])
                    self._bytes[n] = nb[0]
                else:
                    ans = []
                    for b1 in nb:
                        setbyte(self.guess, n+3, b1)
                        for b2 in nnb:
                            count += 1
                            setbyte(self.guess, n+4, b2)
                            a = gauss(self.guess_scaler(self._guess_x), self._gauss_sd)
                            #a = np.clip(a, self.black*self.scale, 256*self.scale)
                            a = normalise(a)
                            diff = np.sum(np.square(a-target))
                            ans.append((diff,b1,b2))

                    ans.sort()
                    setbyte(self.guess, n+3, ans[0][1])
                    self._bytes[n] = ans[0][1]

            # if this iteration didn't produce a change in the answer
            # then the next one won't either, so stop.
            if (self._bytes == self._oldbytes).all():
                break
            self._oldbytes = self._bytes

        #print count
        #do_print("".join([chr(x) for x in self._bytes]))
        sys.stdout.write("".join([chr(x) for x in self._bytes]))
        sys.stdout.flush()
        return True


if __name__ == '__main__':
    datapath = sys.argv[1]
    for frame in range(0, 200000, 1):
      try:
        frame = "%08d" % frame
        f = file(datapath+'/'+frame+'.vbi').read()
        for line in range(12)+range(16,24):
        #for line in [3]:
            offset = line*2048
            vbiraw = np.array(np.fromstring(f[offset:offset+2048], dtype=np.uint8), dtype=np.float)
            v = Vbi(vbiraw)
            c2 = c1 = c0 = time.time()
            if v.find_offset_and_scale():
                c2 = c1 = time.time()
                if v.deconvolve():
                    c2 = time.time()
                    sys.stderr.write("%f, %f, %f\n" % (c1-c0, c2-c1, c2-c0))

      except IOError:
        pass




