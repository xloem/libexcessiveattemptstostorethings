#!/usr/bin/env python3

import asyncio

from honorableneeded import bitcoin

async def main():
    privkey = bitcoin.hex2privkey('088412ca112561ff5db3db83e2756fe447d36ba3c556e158c8f016a2934f7279')
    print(bitcoin.privkey2addr(privkey))

asyncio.run(main())
