# -*- coding: utf-8 -*-
"""
Created on Wed Dec 18 04:43:19 2019

@author: Kyle
"""

#import matplotlib.pyplot as plt
import time
import threading
from pynput import keyboard
import curses

class CHIP9(object):
    regMap = {0: 'B', 1: 'C', 2: 'D', 3: 'E', 4: 'H', 5: 'L', 6: 'M', 7: 'A'}
    def pair(r1, r2):
        return ((r1 << 8) | r2) & 0xffff
    
    def __init__(self):
        self.reset(False)
        self.mem = []   #memory or memory-mapped I/O devices interfaced with the CPU
        self.l = None
        self.serIN = []     #serial input buffer
        self.m = None
        return
    
    def reset(self, go):
        self.regs = {'B': 0xff, 'C': 0xff, 'D': 0xff, 'E': 0xff, 'H': 0xff, 'L': 0xff, 'A': 0xff}
        self.F = 0xf0   #bit 7 = sign, bit 6 = sign, bit 5 = auxiliary carry, bit 4 = carry
        self.PC = 0x0000
        self.SP = 0xffff
        if go:
            self.go()
        
        return
    
    def fetch(self, i):
        assert i > 0
        r = []
        j = 0
        while j < i:
            r.append(self.mread(self.PC))
            self.PC = (self.PC + 1) & 0xffff
            j += 1
            
        return r
    
    def regread(self, r):
        assert r >= 0 and r < 8
        regName = CHIP9.regMap[r]
        if regName == 'M':
            return self.mread(CHIP9.pair(self.regs['H'], self.regs['L']))
        
        return self.regs[regName]
    
    def regwrite(self, r, v):
        assert r >= 0 and r < 8
        regName = CHIP9.regMap[r]
        if regName == 'M':
            self.mwrite(CHIP9.pair(self.regs['H'], self.regs['L']), v)
        else:
            self.regs[regName] = v & 0xff
            
        return
    
    def mread(self, addr):
        assert addr >= 0x0000 and addr <= 0xffff
        for d in self.mem:
            if addr >= d.base and addr < d.cap and d.r:
                return d.read(addr)
            
        self.l.stop()
        raise ValueError("No memory at address 0x%04x exists" %addr)
    
    def mwrite(self, addr, val):
        assert addr >= 0x0000 and addr <= 0xffff
        suc = False
        for d in self.mem:
            if addr >= d.base and addr < d.cap and d.w:
                d.write(addr, val & 0xff)
                suc = True
                break
            
        if not suc:
            self.l.stop()
            raise ValueError("No memory at address 0x%04x exists" % addr)
            
        return
    
    def inSer(self, c):
        x = ord(c)
        assert x >= 0 and x <= 0xff
        self.serIN.append(x)
        return
    
    def genEM(self, pres, pres_arg):
        fmtStr = pres
        fmts = list(pres_arg)
        fmtStr += "=============DEBUG=============\n"
        fmtStr += "PC | 0x%04x\n"
        fmts.append(self.PC)
        fmtStr += "SP | 0x%04x\n"
        fmts.append(self.SP)
        for k in self.regs:
            fmtStr += "%s  | 0x%02x\n"
            fmts += [k, self.regs[k]]
            
        #flag pretty-print
        fmtStr += "F  | "
            
        if self.isZero():
            fmtStr += "Z|"
        else:
            fmtStr += "nz|"
            
        if self.isNegative():
            fmtStr += "N|"
        else:
            fmtStr += "nn|"
            
        if self.isHalfCarry():
            fmtStr += "HC|"
        else:
            fmtStr += "nhc|"
            
        if self.isCarry():
            fmtStr += "C\n"
        else:
            fmtStr += "nc\n"
            
        return fmtStr % tuple(fmts)
    
    def isCarry(self):
        return not self.F & (1 << 4) == 0
    
    def isHalfCarry(self):
        return not self.F & (1 << 5) == 0
    
    def isNegative(self):
        return not self.F & (1 << 6) == 0
    
    def isZero(self):
        return not self.F & (1 << 7) == 0
    
    def perfOp(self, x, y, r, r_size, which):
        if 'C' in which:
            if (x ^ y ^ r) & (1 << r_size) == 0:
                self.F &= ~(1 << 4)     #no carry out
            else:
                self.F |= (1 << 4)      #carry out
                
        if 'H' in which:
            if (x ^ y ^ r) & (1 << 4) == 0:
                self.F &= ~(1 << 5)     #no half carry (lower nibble)
            else:
                self.F |= (1 << 5)      #half carry (lower nibble)
                
        if 'N' in which:
            if r & (1 << (r_size - 1)) == 0:
                self.F &= ~(1 << 6)     #no sign (negative)
            else:
                self.F |= (1 << 6)      #sign (negative)
                
        if 'Z' in which:
            if r % (1 << r_size) != 0:
                self.F &= ~(1 << 7)     #not zero
            else:
                self.F |= (1 << 7)      #zero
        
        if r_size == 8:
            return r & 0xff
        elif r_size == 16:
            return r & 0xffff
        else:
            raise ValueError(self.genEM("Size %d not allowed as return type", [r_size]))
    
    def ALUop(self, x, y, op):
        assert op >= 0 and op < 16
        if op == 0:     #8-bit addition
            return self.perfOp(x, y, x + y, 8, "CHNZ")
        
        if op == 1 or op == 5:     #8-bit subtraction / compare
            return self.perfOp(x, y, x - y, 8, "CHNZ")
        
        if op == 2:     #8-bit AND
            res = self.perfOp(x, y, x & y, 8, "NZ")
            self.F &= ~0x110000
            return res
        
        if op == 3:     #8-bit OR
            res = self.perfOp(x, y, x | y, 8, "NZ")
            self.F &= ~0x110000
            return res
        
        if op == 4:     #8-bit XOR
            res = self.perfOp(x, y, x ^ y, 8, "NZ")
            self.F &= ~0x110000
            return res
        
        if op == 6:     #8-bit and 16-bit addition
            return self.perfOp(x, y, x + y, 16, "CHNZ")
        
        if op == 7:     #8-bit and 16-bit addition (set no flags)
            return self.perfOp(x, y, x + y, 16, '')
        
        if op == 8:     #8-bit SIGNED compare                
            self.perfOp(x, y, x - y, 8, 'CHNZ')
            # need to adjust flags in case of signed operands
            if x > 0x7f and y <= 0x7f:
                self.F |= (1 << 6)
            elif x <= 0x7f and y > 0x7f:
                self.F &= ~(1 << 6)
                
            return
        
        raise ValueError(self.genEM("ALU: Undefined ALU op %d", [op]))
    
    def go(self):
        while True:
            cur_instr = self.fetch(1)[0]   #instruction fetch
            if cur_instr == 0x00:       #NOP
                continue
            elif cur_instr == 0x6c:     #HCF
                raise ValueError(self.genEM("HCF: Halted and caught fire!", []))
            elif cur_instr == 0x08:     #CLRFLAG
                self.F = 0x00
            elif cur_instr == 0x1e:     #CALL a16
                dataGot = self.fetch(2)
                self.mwrite(self.SP + 1, self.PC >> 8)
                self.mwrite(self.SP, self.PC & 0xff)
                self.SP = (self.SP - 2) & 0xffff
                self.PC = CHIP9.pair(dataGot[1], dataGot[0])
            elif cur_instr == 0x0e:     #RET
                self.SP = (self.SP + 2) & 0xffff
                self.PC = CHIP9.pair(self.mread(self.SP + 1), self.mread(self.SP))
            elif cur_instr == 0xe0:     #SIN
                x = 0
                if len(self.serIN):
                    x = self.serIN[0]
                    del self.serIN[0]
                    
                self.regwrite(7, x)
            elif cur_instr == 0xf0:     #CLRSCR
                self.m.clear()
#                print("Screen Cleared")     #DEBUG: SCR
            elif cur_instr == 0xf1:     #DRAW
                self.m.draw(self.regread(0), self.regread(1), self.regread(7))
#                print("Draw A = 0x%02x, B = 0x%02x, C = 0x%02x" % (self.regread(7), self.regread(0), self.regread(1)))  #DEBUG: SCR    
            elif cur_instr == 0xe1:     #SOUT
                print(chr(self.regread(7)), end = '')       #turn OFF when executing in terminal
                time.sleep(0.05)
#                print("| 0x%04x" % (self.PC))       #DEBUG
            
            # fetch one extra byte of data
            elif cur_instr in [0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80, 0x90, 0xa7, 0xb7, 0xc7, 0xd7, 0xe7, 0xf7]:
                dataGot = self.fetch(1)[0]
                if cur_instr & 0x0f == 0:       #LDI r8, i8
                    self.regwrite((cur_instr >> 4) - 0x02, dataGot)
                else:
                    t = self.ALUop(self.regread(7), dataGot, (cur_instr >> 4) - 0x0a)   #CMPI i8
                    if cur_instr != 0xf7:       #ADDI i8   #SUBI i8  #ANDI i8
                        self.regwrite(7, t)     #ORI i8   #XORI i8
                        
            # fetch two extra bytes of data
            elif cur_instr in [0x21, 0x31, 0x41, 0x22]:     #LDX r16, i16
                dataGot = self.fetch(2)
                if cur_instr & 0x0f == 1:
                    hreg = (cur_instr >> 3) - 0x04
                    self.regwrite(hreg, dataGot[1])
                    self.regwrite(hreg + 1, dataGot[0])
                else:
                    self.SP = CHIP9.pair(dataGot[1], dataGot[0])
                    
            elif (cur_instr & 0x0f) in [0x09, 0x0a, 0x0b, 0x0c]:        #MOV r8, r8
                r_d = (((cur_instr & 0x07) << 1) | (cur_instr >> 7)) - 2
                r_s = (cur_instr & 0x70) >> 4
                self.regwrite(r_d, self.regread(r_s))
            elif cur_instr in [0x81, 0x91, 0xa1, 0xb1, 0xc1, 0xd1, 0xc0, 0xd0]:     #PUSH r8
                if cur_instr == 0xc0:
                    self.mwrite(self.SP, self.regread(6))
                elif cur_instr == 0xd0:
                    self.mwrite(self.SP, self.regread(7))
                else:
                    self.mwrite(self.SP, self.regread((cur_instr >> 4) - 0x08))
                    
                self.SP = (self.SP - 2) & 0xffff
            elif cur_instr in [0x51, 0x61, 0x71]:   #PUSH r16
                hreg = (cur_instr >> 3) - 0x0a
                self.mwrite(self.SP + 1, self.regread(hreg))
                self.mwrite(self.SP, self.regread(hreg + 1))
                self.SP = (self.SP - 2) & 0xffff
            elif cur_instr in [0x82, 0x92, 0xa2, 0xb2, 0xc2, 0xd2, 0xc3, 0xd3]:     #POP r8
                self.SP = (self.SP + 2) & 0xffff
                b = self.mread(self.SP)
                if cur_instr == 0xc3:
                    self.regwrite(6, b)
                elif cur_instr == 0xd3:
                    self.regwrite(7, b)
                else:
                    self.regwrite((cur_instr >> 4) - 0x08, b)
            elif cur_instr in [0x52, 0x62, 0x72]:   #POP r16
                hreg = (cur_instr >> 3) - 0x0a
                self.SP = (self.SP + 2) & 0xffff
                self.regwrite(hreg, self.mread(self.SP + 1))
                self.regwrite(hreg + 1, self.mread(self.SP))
            elif cur_instr in [0xed, 0xfd]:         #MOV r16, r16
                hreg = (cur_instr >> 3) - 0x1d
                self.regwrite(4, self.regread(hreg))
                self.regwrite(5, self.regread(hreg + 1))
            elif cur_instr & 0x0f == 0x04:
                o = cur_instr >> 4
                if o < 8:       #ADD r8
                    self.regwrite(o, self.ALUop(self.regread(o), self.regread(7), 0))
#                    print(self.genEM('INSIDE ADD', []))     #DEBUG
                else:           #SUB r8
                    self.regwrite(o - 8, self.ALUop(self.regread(o - 8), self.regread(7), 1))
                    
            elif cur_instr in [0x83, 0x93, 0xa3]:       #ADDX r16
                hreg = (cur_instr >> 3) - 0x10
                r = self.ALUop(self.regread(7), CHIP9.pair(self.regread(hreg), self.regread(hreg + 1)), 6)
                self.regwrite(hreg, r >> 8)
                self.regwrite(hreg + 1, r & 0xff)
            elif cur_instr in [0x03, 0x13, 0x23, 0x33, 0x43, 0x53, 0x63, 0x73]:     #INC r8
                r = cur_instr >> 4
                self.regwrite(r, self.ALUop(self.regread(cur_instr >> 4), 1, 0))
            elif cur_instr in [0xa8, 0xb8, 0xc8]:           #INX r16
                hreg = (cur_instr >> 3) - 0x15
                r = self.ALUop(CHIP9.pair(self.regread(hreg), self.regread(hreg + 1)), 1, 7)
                self.regwrite(hreg, r >> 8)
                self.regwrite(hreg + 1, r & 0xff)
            elif cur_instr in [0x07, 0x17, 0x27, 0x37, 0x47, 0x57, 0x67, 0x77]:     #DEC r8
                r = cur_instr >> 4
                self.regwrite(r, self.ALUop(self.regread(cur_instr >> 4), 1, 1))
            elif cur_instr & 0x0f == 0x05:
                o = cur_instr >> 4
                if o < 8:       #AND r8
                    self.regwrite(o, self.ALUop(self.regread(o), self.regread(7), 2))
                else:           #OR r8
                    self.regwrite(o - 8, self.ALUop(self.regread(o - 8), self.regread(7), 3))
                    
            elif cur_instr & 0x0f == 0x06:
                o = cur_instr >> 4
                if o < 8:       #XOR r8
                    self.regwrite(o, self.ALUop(self.regread(o), self.regread(7), 4))
                else:           #CMP r8
                    self.ALUop(self.regread(o - 8), self.regread(7), 5)
                    
            elif cur_instr in [0x0d, 0x1d, 0x2d, 0x3d, 0x4d, 0x5d, 0x6d, 0x7d]:     #CMPS r8
                self.ALUop(self.regread(cur_instr >> 4), self.regread(7), 8)
            elif cur_instr & 0x0f == 0x0f or cur_instr in [0xee, 0xfe]:
                if cur_instr & 0xf0 <= 0x80:
                    dataGot = self.fetch(2)
                    if any([cur_instr == 0x0f,          #JMP a16
                            (cur_instr == 0x1f and self.isZero()),  #JZ a16
                            (cur_instr == 0x2f and not self.isZero()),  #JNZ a16
                            (cur_instr == 0x3f and self.isNegative()),  #JN a16
                            (cur_instr == 0x4f and not self.isNegative()),  #JNN a16
                            (cur_instr == 0x5f and self.isHalfCarry()),     #JH a16
                            (cur_instr == 0x6f and not self.isHalfCarry()), #JNH a16
                            (cur_instr == 0x7f and self.isCarry()), #JC a16
                            (cur_instr == 0x8f and not self.isCarry())]):   #JNC a16
                        self.PC = CHIP9.pair(dataGot[1], dataGot[0])
                        
                else:
                    dataGot = self.fetch(1)[0]
#                    print(self.genEM('Inside of conditional jump.', []))       #DEBUG
                    if any([cur_instr == 0x9f,          #JMP a8
                            (cur_instr == 0xaf and self.isZero()),  #JZ a8
                            (cur_instr == 0xbf and not self.isZero()),  #JNZ a8
                            (cur_instr == 0xcf and self.isNegative()),  #JN a8
                            (cur_instr == 0xdf and not self.isNegative()),  #JNN a8
                            (cur_instr == 0xef and self.isHalfCarry()),     #JH a8
                            (cur_instr == 0xff and not self.isHalfCarry()), #JNH a8
                            (cur_instr == 0xee and self.isCarry()), #JC a8
                            (cur_instr == 0xfe and not self.isCarry())]):   #JNC a8
                        if dataGot > 0x7f:
                            dataGot -= 0x100
                            
                        self.PC = (self.PC + dataGot) & 0xffff
                        
            elif cur_instr in [0x18, 0x28, 0x38, 0x48, 0x58, 0x68, 0x78, 0x88]:     #SETFLAG f, b
                flid = 7 - (((cur_instr >> 4) - 1) >> 1)
                if (cur_instr >> 4) % 2 == 0:
                    self.F &= ~(1 << flid)
                else:
                    self.F |= (1 << flid)
                    
            #comment out below during actual run -- illops produce no effect
            else:
                if cur_instr not in []:
                    self.l.stop()
                    raise ValueError(self.genEM("ILLOP: Undefined op code 0x%02x\n", [cur_instr]))
                
    def attachListener(self, listener):
        self.l = listener
        return
    
    def attachMem(self, device):
        assert isinstance(device, memDevice)
        assert device not in self.mem
        self.mem.append(device)
        return
    
    def attachMonitor(self, monitor):
        self.m = monitor
        return
    

# template for generic memory device
# it is the USER'S RESPONSIBILITY to ensure no data collisions between devices
class memDevice(object):
    def __init__(self, addrBase, addrCap, inDev, outDev):
        assert addrBase >= 0x0000 and addrBase <= 0xffff
        assert addrCap >= 0x0000 and addrCap <= 0xffff + 1
        assert addrCap > addrBase
        self.base = addrBase
        self.cap = addrCap
        self.buf = (addrCap - addrBase) * [0]
        self.r = inDev
        self.w = outDev
        return
    
    def write(self, addr, val):
        assert addr >= self.base and addr < self.cap
        assert self.w
        self.buf[addr - self.base] = val & 0xff
        return
        
    def read(self, addr):
        assert addr >= self.base and addr < self.cap
        assert self.r
        return self.buf[addr - self.base]
    

# a flash memory device to hold code and / or data, which can be written and read from
class Flash(memDevice):
    def __init__(self, base, cap, srcFile = ''):
        assert base >= 0x0000 and base <= 0xffff
        assert cap >= 0x0000 and cap <= 0xffff + 1
        assert cap > base
        super(Flash, self).__init__(base, cap, True, True)
        if len(srcFile):
            with open(srcFile, "rb") as f:
                progTxt = f.read()
                for i in range(base, cap):
                    if i - base < len(progTxt):
                        self.write(i, progTxt[i - base])
                    else:
                        self.write(i, 0x00)
        else:
            for i in range(base, cap):
                self.write(i, 0x00)
        
        return
    

class Joystick(memDevice):
    keymap = {"up": 7, "left": 6, "down": 5, "right": 4, 'A': 3, 'B': 2, "select": 1, "start": 0}
    def __init__(self, addr):
        assert addr >= 0x0000 and addr <= 0xffff
        super(Joystick, self).__init__(addr, addr + 1, False, True)
        return
    
    def action(self, key, pressed):
        button = Joystick.keymap[key]
        if pressed:
            self.write(self.base, self.buf[0] | (1 << button))
            return
        
        self.write(self.base, self.buf[0] & ~(1 << button))
        return
    

class Monitor(object):
    def subb(s):
        return s.replace('0', chr(0xdb)).replace('1', ' ')
    
    def __init__(self, freq):
        self.freq = freq
        self.screen = curses.initscr()
        curses.resize_term(100, 150)
#        curses.initscr()
#        self.screen = curses.newwin(64, 128, 0, 0)
        curses.curs_set(0)
        self.refresh()
        return
    
    def clear(self):
        self.screen.clear()
        for y in range(40):
            for x in range(16):
                self.screen.addstr(y, 8 * x, Monitor.subb("11111111"))
                                
        return
    
    def draw(self, y, x, row):
        if y < 20 or y >= 60 or x <= -8 or x >= 128:
            return  #these cases will not print anything to the screen
        
        c = 8
        if x < 0:
            row = (row << (-x)) & 0xff
            c = 8 + x
            
        if x > 120:
            row >>= x - 120
            c = 128 - x
            
        self.screen.addstr(y - 20, x, Monitor.subb(format(row, '0' + str(c) + 'b')))
        return
    
    def refresh(self):
        threading.Timer(1 / self.freq, self.refresh).start()
        self.screen.refresh()
        return
    

#####################################################################
### Starting of main code                                           #
#####################################################################
myChip9 = CHIP9()
myJoystick = Joystick(0xf000)
myChip9.attachMem(myJoystick)

def on_press(key):
    if key == keyboard.Key.up:
        myJoystick.action("up", True)
    elif key == keyboard.Key.left:
        myJoystick.action("left", True)
    elif key == keyboard.Key.down:
        myJoystick.action("down", True)
    elif key == keyboard.Key.right:
        myJoystick.action("right", True)
    elif str(key)[1] == 'a':
        myJoystick.action("A", True)
    elif str(key)[1] == 'z':
        myJoystick.action("B", True)
    elif str(key)[1] == '[':
        myJoystick.action("select", True)
    elif str(key)[1] == ']':
        myJoystick.action("start", True)
    else:
        myChip9.inSer(str(key)[1])
        
    return

def on_release(key):
    if key == keyboard.Key.up:
        myJoystick.action("up", False)
    elif key == keyboard.Key.left:
        myJoystick.action("left", False)
    elif key == keyboard.Key.down:
        myJoystick.action("down", False)
    elif key == keyboard.Key.right:
        myJoystick.action("right", False)
    elif str(key)[1] == 'a':
        myJoystick.action("A", False)
    elif str(key)[1] == 'b':
        myJoystick.action("B", False)
    elif str(key)[1] == '[':
        myJoystick.action("select", False)
    elif str(key)[1] == ']':
        myJoystick.action("start", False)
        
    return

listener = keyboard.Listener(on_press = on_press, on_release = on_release)
myChip9.attachListener(listener)
listener.start()

myChip9.attachMem(Flash(0x0000, 0x0400, "CHIP9_bootrom"))
myChip9.attachMem(Flash(0x0597, 0x8000, "CHIP9_rom"))
myChip9.attachMonitor(Monitor(60))      #
myChip9.attachMem(Flash(0x0000, 0x10000))
myChip9.reset(True)     #run the bootloader





######################################################################
#### Testing monitor                                                 #
######################################################################
#m_test = Monitor(60)
#
#while True:
#    m_test.clear()
#    time.sleep(0.5)
#    print("Monitor is cleared")
#    m_test.draw(0x00, 0x00, 0xaa)
#    time.sleep(0.5)
