    .section .entry,"ax",@progbits
    .global _start
    .align 4
_start:
    rsil a2, 15
    movi a1, 0x3ffc0000
    call8 bridge_main
1:  j 1b
