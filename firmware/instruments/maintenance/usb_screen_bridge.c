/* Classic ESP32 RAM-only maintenance bridge. No flash, Wi-Fi or motion code. */
#include <stdint.h>

#define REG(address) (*(volatile uint32_t *)(address))
#define U0 0x3ff40000u
#define U2 0x3ff6e000u
#define FIFO0 0x60000000u
#define FIFO2 0x6002e000u

static unsigned rx_count(uint32_t uart) {
    /* ESP32 APB FIFO reads require pointer-based accounting (IDF uart_ll). */
    uint32_t status = REG(uart + 0x60);
    unsigned rd = (status >> 2) & 0x7ff, wr = (status >> 13) & 0x7ff;
    if (wr != rd) return (wr - rd) & 127;
    return (REG(uart + 0x1c) & 255) ? 128 : 0;
}

static unsigned tx_count(uint32_t uart) { return (REG(uart + 0x1c) >> 16) & 255; }

static void usb_text(const char *text) {
    while (*text) {
        while (tx_count(U0) >= 120) {}
        REG(FIFO0) = (uint8_t)*text++;
    }
}

static void output_low(unsigned pin, unsigned mux_offset) {
    REG(pin < 32 ? 0x3ff4400c : 0x3ff44018) = 1u << (pin & 31);
    uint32_t mux = 0x3ff49000u + mux_offset;
    REG(mux) = (REG(mux) & ~0x7380u) | 0x2080;
    REG(0x3ff44530u + pin * 4) = (1u << 10) | 256;
    REG(pin < 32 ? 0x3ff44024 : 0x3ff44030) = 1u << (pin & 31);
}

void __attribute__((noreturn)) bridge_main(void) {
    /* Physical actuator power must also be disconnected by the operator. */
    output_low(12, 0x34);
    output_low(13, 0x38);
    output_low(15, 0x3c);
    output_low(21, 0x7c);
    output_low(25, 0x24);
    output_low(26, 0x28);
    output_low(27, 0x2c);
    output_low(33, 0x20);

    /* No automatic reboot into the old application on timeout or error. */
    REG(0x3ff480a4) = 0x50d83aa1;
    REG(0x3ff4808c) = 0;
    REG(0x3ff480a4) = 0;
    REG(0x3ff5f064) = 0x50d83aa1;
    REG(0x3ff5f048) = 0;
    REG(0x3ff5f064) = 0;
    REG(0x3ff60064) = 0x50d83aa1;
    REG(0x3ff60048) = 0;
    REG(0x3ff60064) = 0;

    REG(0x3ff000c0) |= (1u << 23) | (1u << 24);
    REG(0x3ff000c4) &= ~(1u << 23);
    REG(U2 + 0x0c) = 0;
    REG(U2 + 0x18) = 0;
    REG(U2 + 0x14) = REG(U0 + 0x14);
    REG(U2 + 0x58) = (1u << 7) | (1u << 3);
    REG(U2 + 0x20) = (REG(U0 + 0x20) & (1u << 27)) | (1u << 25) | 0x1c;
    REG(U2 + 0x24) = 0;
    REG(0x3ff4904c) = (REG(0x3ff4904c) & ~0x7380u) | 0x2300;
    REG(0x3ff49050) = (REG(0x3ff49050) & ~0x7380u) | 0x2000;
    REG(0x3ff44448) = 0x80 | 16;
    REG(0x3ff44574) = (1u << 10) | 198;
    REG(0x3ff44028) = 1u << 16;
    REG(0x3ff44024) = 1u << 17;

    while (rx_count(U2)) (void)REG(U2);
    while (rx_count(U0)) (void)REG(U0);
    REG(U0 + 0x10) = 0xffffffff;
    REG(U2 + 0x10) = 0xffffffff;
    /* Let ROM MEM_END finish before our banner is sent. */
    for (volatile unsigned i = 0; i < 200000; ++i) {}
    usb_text("\r\nIMYTEST_RAM_BRIDGE_V1_READY\r\n");
    for (;;) {
        /* Overflow, parity or framing errors: stop rather than corrupt a TFT. */
        if ((REG(U0 + 4) | REG(U2 + 4)) & 0x1c) {
            usb_text("\r\nIMYTEST_RAM_BRIDGE_ERROR\r\n");
            for (;;) {}
        }
        if (rx_count(U0) && tx_count(U2) < 120) REG(FIFO2) = REG(U0) & 255;
        if (rx_count(U2) && tx_count(U0) < 120) REG(FIFO0) = REG(U2) & 255;
    }
}
