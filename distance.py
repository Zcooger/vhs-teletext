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

# This program analyses recovered packets to find similar matches using hamming
# distance.

import sys
import numpy as np
from scipy.spatial.distance import hamming

import pylab

def hamming_all(target, max_diff, filename):
    f = file(filename)
    ans = []
    while True:
        packet = f.read(42)
        if len(packet) != 42:
            ans = np.column_stack(ans)
            #print ans.shape
            auni = np.unique(ans)
            mode = np.zeros(42, dtype=np.uint8)
            counts = np.zeros(42)
            for k in auni:
                count = (ans==k).sum(-1)
                mode[count>counts] = k
                counts[count>counts] = count[count>counts] 
            sys.stdout.write("".join([chr(x) for x in mode]))
            sys.stdout.flush()


            return

        packet = np.fromstring(packet, dtype=np.uint8)
        if (target[:2] == packet[:2]).all():
          if((target != packet).sum() <= max_diff):
            ans.append(packet)
            #sys.stdout.write("".join([chr(x) for x in packet]))
            #sys.stdout.flush()


if __name__ == '__main__':

    filename = sys.argv[1]

    try:
        f = file(filename)
        while True:
            
            packet = np.fromstring(f.read(42), dtype=np.uint8)
            hamming_all(packet, 5, filename)
    except IOError:
        exit(0)

