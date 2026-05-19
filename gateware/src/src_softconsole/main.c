/*******************************************************************************
 * Interlock firmware — iteration 1: observation pass.
 *
 * Adapted from Microsemi/Microchip AN4623 (DG0799) iog_cdr/main.c.
 *
 * Changes from AN4623 baseline:
 *   - UART_init moved to the very top of main() so we see boot output.
 *   - MDIO bus scan: read PHY ID at every MDIO address 0..31 and print
 *     anything that responds. Tells us where port 0 and port 1 PHYs live
 *     without guessing.
 *   - Print progress around each major init step.
 *   - Read and print final port 0 link state after autoneg.
 *   - Idle loop polls port 0 status once per ~1s, prints link bit.
 *   - Tiny hex/dec uart helpers (no snprintf to keep TCM usage low).
 *   - "Hello World" loop removed (replaced by status-polling loop).
 *
 * No port-1 MAC or PHY init in this iteration — the bus scan results
 * determine port-1 PHY addresses for iteration 2.
 *
 * Original copyright header retained per Microsemi licence.
 */
/*******************************************************************************
 * (c) Copyright 2016-2017 Microsemi Corporation. All rights reserved.
 *
 *  Simple IOD CDR 1G loop back example program.
 */

#include "drivers/CoreUARTapb/core_uart_apb.h"
#include "miv_rv32_hal/miv_rv32_hal.h"
#include "sample_hw_platform.h"

extern void configure_zl30364(void);

/*
 * CoreTSE_1 lives at APB slot 3. The slot layout from hw_platform.h
 * (TSE at 0x60000000, UART at 0x60001000, SPI at 0x60002000) shows
 * 4 KB-per-slot striding, so slot 3 sits at 0x60003000. The interlock
 * SmartDesign wires CoreTSE_1's APBS to CoreAPB3 slave 3, confirming.
 */
#define TSE1_BASEADDR 0x60003000UL

/*
 * CoreTSE register offsets used here (subset of the IP's CSR map).
 *   0x000 / 0x004     MAC_CONFIG_1 / 2
 *   0x020             MII Management Configuration (MDC prescaler)
 *   0x024             MII MGMT Command  (1 = start read, 0 = idle/write)
 *   0x028             MII MGMT Address  {phy_addr[4:0], 3'b0, reg_addr[4:0]}
 *   0x02C             MII MGMT TX data  (16-bit write payload)
 *   0x030             MII MGMT RX data  (16-bit read result)
 *   0x034             MII MGMT Indicators — bit 0 = busy
 */

UART_instance_t g_uart;
extern void delay(uint32_t div);

/*--------------------------- UART print helpers -----------------------------*/

static void uart_print(const char *s)
{
    UART_polled_tx_string(&g_uart, (const uint8_t *)s);
}

static void uart_print_hex16(uint16_t v)
{
    static const char hex[] = "0123456789ABCDEF";
    char buf[7];
    buf[0] = '0';
    buf[1] = 'x';
    buf[2] = hex[(v >> 12) & 0xF];
    buf[3] = hex[(v >>  8) & 0xF];
    buf[4] = hex[(v >>  4) & 0xF];
    buf[5] = hex[(v >>  0) & 0xF];
    buf[6] = '\0';
    uart_print(buf);
}

static void uart_print_dec(uint32_t v)
{
    char buf[11];
    int i = 10;
    buf[i--] = '\0';
    if (v == 0) {
        buf[i--] = '0';
    } else {
        while (v > 0) { buf[i--] = (char)('0' + (v % 10)); v /= 10; }
    }
    uart_print(&buf[i + 1]);
}

/*--------------------------- MDIO helpers -----------------------------------*/

static inline uint16_t mdio_addr(uint8_t phy, uint8_t reg)
{
    return (uint16_t)(((uint16_t)phy << 8) | (reg & 0x1F));
}

static uint16_t mdio_read(uint32_t tse_base, uint8_t phy, uint8_t reg)
{
    *(volatile unsigned int *)(tse_base + 0x028) = mdio_addr(phy, reg);
    *(volatile unsigned int *)(tse_base + 0x024) = 0x1;
    while ((*(volatile unsigned int *)(tse_base + 0x034)) != 0) { }
    uint16_t v = (uint16_t) *(volatile unsigned int *)(tse_base + 0x030);
    *(volatile unsigned int *)(tse_base + 0x024) = 0x0;
    return v;
}

static void mdio_write(uint32_t tse_base, uint8_t phy, uint8_t reg, uint16_t val)
{
    *(volatile unsigned int *)(tse_base + 0x028) = mdio_addr(phy, reg);
    *(volatile unsigned int *)(tse_base + 0x02C) = val;
    while ((*(volatile unsigned int *)(tse_base + 0x034)) != 0) { }
}

/*--------------------------- MDIO bus scan ----------------------------------*/

/*
 * Sweep MDIO addresses 0..31 on CoreTSE_0 (the only MDIO master wired to
 * the VSC8575). Print every address whose PHY ID register isn't all-ones
 * or all-zeros. VSC8575 reports ID1 = 0x0007, ID2 = 0x0429 in the upper
 * nibbles (vendor OUI 00:01:C1 with revision tail) — adjust expectations
 * once the actual values land on the UART.
 */
static void mdio_scan(uint32_t tse_base)
{
    uart_print("[scan] sweeping MDIO 0..31 on TSE @ ");
    uart_print_hex16((uint16_t)(tse_base >> 16));
    uart_print("....\r\n");
    for (uint8_t addr = 0; addr < 32; addr++) {
        uint16_t id1 = mdio_read(tse_base, addr, 2);  /* PHY ID register 1 */
        uint16_t id2 = mdio_read(tse_base, addr, 3);  /* PHY ID register 2 */
        if (id1 != 0xFFFF && (id1 != 0x0000 || id2 != 0x0000)) {
            uart_print("[scan]   addr=");
            uart_print_dec(addr);
            uart_print("  ID1=");
            uart_print_hex16(id1);
            uart_print("  ID2=");
            uart_print_hex16(id2);
            uart_print("\r\n");
        }
    }
    uart_print("[scan] done\r\n");
}

/*--------------------------- AN4623 originals ------------------------------*/
/*
 * The four functions below (Phy_advertise, phy_autonegotiation, phy_init,
 * tse_init) are unchanged from AN4623's iog_cdr/main.c. They configure
 * port 0 only and reference PHY addresses 28 (copper) and 18 (SGMII) on
 * the VSC8575. Once the MDIO scan confirms port 1 addresses, iteration 2
 * will add analogous functions parameterised on PHY addr + base.
 */

void Phy_advertise(void)
{
  uint32_t phy_reg = 0xFFFF;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C04;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg &= ~(0x1E);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C04;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C09;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg |= 0x200;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C09;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);
}

void phy_autonegotiation(void)
{
  uint32_t phy_reg = 0xFFFF;
  uint16_t autoneg_complete;
  volatile uint32_t copper_aneg_timeout = 1000000u;
  volatile uint32_t sgmii_aneg_timeout = 100000u;
  uint8_t copper_link_up;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg |= 0x1200;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  do {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C01;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    autoneg_complete = phy_reg & 0x0020u;
    --copper_aneg_timeout;
  } while(!autoneg_complete && (copper_aneg_timeout != 0u));

  for (volatile uint32_t i = 0; i < 100000; i++);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C01;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  copper_link_up = phy_reg & 0x0004;

  if(copper_link_up != 0u)
  {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1200;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    phy_reg |= 0x1000;

    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1200;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1200;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    phy_reg |= 0x0200;

    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1200;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    do {
      *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1201;
      *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
      while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

      phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
      *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

      autoneg_complete = phy_reg & 0x0020;
      --sgmii_aneg_timeout;
    } while((!autoneg_complete) && (sgmii_aneg_timeout != 0u));
  }
}

void phy_init (void)
{
  volatile uint16_t phy_reg_0;
  volatile uint16_t temp;
  volatile uint16_t  id1=0,id2=0,phy_mac_reg = 0;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C02;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  id1 = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C03;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  id2 = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  /* 16E3 bit 7 setting to 1 for SERDES MAC AN EN */
  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0003;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C10;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_mac_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_mac_reg |= 0x80;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C10;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_mac_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  /* Set Register 31 to 0 */
  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0010;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_mac_reg = 0x80F0;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C12;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_mac_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  while(1)
  {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C12;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    temp = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    if((temp & 0x8000) == 0)
    {
      break;
    }
  }

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg_0 = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg_0 = phy_reg_0 | 0x8000;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg_0;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  while(1)
  {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C00;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    temp = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;
    if((temp & 0x8000) == 0)
    {
      break;
    }
  }

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1C00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  temp = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  (void)id1; (void)id2; (void)temp;
}

/* CoreTSE_0 MAC register init */
void tse_init (void)
{
  uint32_t tse_reg = 0xFFFF;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x000) = 0x00000005;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x004) = 0x00007201;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x040) = 0x6060603C;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x044) = 0xB1C00000;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x048) = 0x0000FF00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x04C) = 0x0FFF0000;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x050) = 0x04000180;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x054) = 0x0680FFFF;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x058) = 0x00000000;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x05C) = 0x0007FFFF;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x1C0) = 0x0000000F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x020) = 0x0007;

  tse_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x20);
  (void)tse_reg;

  phy_init();
}

/*-------------------------- main ------------------------------------------*/

int main(void)
{
    /* Bring UART up first so all subsequent steps are visible. */
    UART_init(&g_uart, COREUARTAPB0_BASE_ADDR,
              BAUD_VALUE_115200, (DATA_8_BITS | NO_PARITY));
    uart_print("\r\n\r\n[boot] interlock firmware iter-1 starting\r\n");

    /* MDIO bus scan via CoreTSE_0 (the only MDIO master wired to VSC8575).
       Catch: CoreTSE_0's MDIO controller is unconfigured at this point —
       the MDC prescaler in MAC reg 0x020 hasn't been set yet. So this scan
       won't work until after tse_init() runs. Calling it after for now. */

    uart_print("[boot] configure_zl30364 (clock generator)\r\n");
    configure_zl30364();
    uart_print("[boot] configure_zl30364 done\r\n");

    uart_print("[boot] tse_init (MAC 0, PHY at 28, includes phy_init)\r\n");
    tse_init();
    uart_print("[boot] tse_init done\r\n");

    /* MDIO is alive now — scan the bus and dump every PHY that responds. */
    mdio_scan(TSE_BASEADDR);

    uart_print("[boot] Phy_advertise (PHY 28 reg 4, 9)\r\n");
    Phy_advertise();
    uart_print("[boot] Phy_advertise done\r\n");

    uart_print("[boot] phy_autonegotiation (PHY 28 reg 0/1, then PHY 18)\r\n");
    phy_autonegotiation();
    uart_print("[boot] phy_autonegotiation done\r\n");

    /* Read and print final state of the port-0 PHYs. */
    uint16_t st_copper = mdio_read(TSE_BASEADDR, 28, 1);
    uint16_t st_sgmii  = mdio_read(TSE_BASEADDR, 18, 1);
    uart_print("[state] PHY28 (copper) status=");
    uart_print_hex16(st_copper);
    uart_print(" link=");
    uart_print_dec((st_copper >> 2) & 1);
    uart_print(" aneg_done=");
    uart_print_dec((st_copper >> 5) & 1);
    uart_print("\r\n");
    uart_print("[state] PHY18 (SGMII)  status=");
    uart_print_hex16(st_sgmii);
    uart_print(" link=");
    uart_print_dec((st_sgmii >> 2) & 1);
    uart_print(" aneg_done=");
    uart_print_dec((st_sgmii >> 5) & 1);
    uart_print("\r\n");

    /* Probe CoreTSE_1: does the MAC at slot 3 respond to a register read?
       If MAC_CONFIG_1 reads back something plausible (not 0xFFFFFFFF, not
       a bus-error hang), the slot mapping is correct. We don't initialize
       CoreTSE_1 yet — iteration 2 once we have the scan data. */
    uart_print("[probe] CoreTSE_1 at ");
    uart_print_hex16((uint16_t)(TSE1_BASEADDR >> 16));
    uart_print("0000: MAC_CONFIG_1 reads ");
    uint32_t tse1_mc1 = *(volatile unsigned int *)(TSE1_BASEADDR + 0x000);
    uart_print_hex16((uint16_t)(tse1_mc1 >> 16));
    uart_print_hex16((uint16_t)tse1_mc1);
    uart_print("\r\n");

    uart_print("[boot] init complete — polling port 0 status\r\n");

    /* Idle loop: poll once per ~1 second and print link bit. */
    uint32_t tick = 0;
    while (1) {
        for (volatile uint32_t i = 0; i < 8000000; i++) { }  /* ~1s at 80 MHz */
        uint16_t st = mdio_read(TSE_BASEADDR, 28, 1);
        uart_print("[poll t=");
        uart_print_dec(tick++);
        uart_print("] PHY28 status=");
        uart_print_hex16(st);
        uart_print(" link=");
        uart_print_dec((st >> 2) & 1);
        uart_print("\r\n");
    }
}
