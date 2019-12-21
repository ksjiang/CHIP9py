# CHIP9py
Proof-of-concept emulator for Intel 8080/85-like CPU with standard keyboard buffering and terminal screen

The CHIP9 is a theoretical 8-bit microcontroller designed by Milkdrop from HTSP and featured a challenge in the "Emulation" category of the [2019 X-MAS CTF](https://xmas.htsp.ro/home). It features a register set identical to that of the Intel 8080/85, with accumulator (`A`), `BC`, `DE`, and `HL` general registers, along with a flags register and 16-bit program counter (`PC`) and stack pointer (`SP`). Full details of the instruction set are available [from the challenge creators](https://drive.google.com/drive/folders/13FEjObT9AE3sLVmeq6G948ASojEzwa97).

The challenge itself consists of uncovering the flag from two binaries, one of which is a "boot ROM" that initializes a system state and jumps to the working ROM, and the other a ROM that displays the flag. While one way to attack this challenge is to simply reverse-engineer the ROMs based on the given documentation (and this would have likely been a more efficient method looking back), the obviously more exciting approach is to build an emulator for the CHIP9 and run the ROMs. Because the processor only features ~200 instructions, a bare-bones Python script emulator was proposed. To emulate the screen output, Python's `curses` library was used to drive a cell-terminal, which refreshes every 1 / 60 second (as specified in the CHIP9 documentation).

The final running speed of the emulator is unacceptable - it takes approximately **3 minutes** to print the image from the boot ROM. It turns out that this is due to a loop in the boot ROM at address `0x002f`

![Loop in Boot ROM](C:\Users\Kyle\Dropbox\Screenshots\Screenshot 2019-12-21 17.16.47.png)

which can be disassembled to the following:

```
0x002f:
	LDI A, 0xff
	ADDX DE
>	JMPNZ 0x002f
```

In other words, 0xff is added onto `DE` until that register pair is `0`. This can take a long time indeed! So, we can speed up the execution by changing the loop condition to a `JMPN` (jump if negative) instead:

![Patched Loop in Boot ROM](C:\Users\Kyle\Dropbox\Screenshots\Screenshot 2019-12-21 17.12.10.png)

Now boot happens very quickly. We load the program ROM into address `0x597`, as requested, and run the program, but run into an issue:
