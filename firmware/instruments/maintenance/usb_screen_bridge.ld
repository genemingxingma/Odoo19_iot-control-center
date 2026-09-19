ENTRY(_start)
MEMORY {
    iram (rx) : ORIGIN = 0x400be000, LENGTH = 0x2000
    dram (rw) : ORIGIN = 0x3ffb0000, LENGTH = 0x8000
}
SECTIONS {
    .text : ALIGN(4) {
        KEEP(*(.entry))
        *(.literal .literal.* .text .text.*)
    } > iram
    .data : ALIGN(4) { *(.rodata .rodata.* .data .data.*) } > dram
    .bss (NOLOAD) : ALIGN(4) { *(.bss .bss.* COMMON) } > dram
    /DISCARD/ : { *(.comment .note.* .eh_frame) }
}
