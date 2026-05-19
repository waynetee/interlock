/*******************************************************************************
 * Interlock firmware — iteration 2: port-1 bring-up, mirrored from port-0.
 *
 * Adapted from Microsemi/Microchip AN4623 (DG0799) iog_cdr/main.c.
 *
 * Strategy for risk reduction: the port-0 init functions are LEFT UNCHANGED
 * (verbatim from AN4623 — we know they work). Port-1 init functions are
 * near-verbatim copies of the port-0 functions, with two constants changed:
 *   - All `0x1C..` MDIO encoded addresses (PHY 28 = copper-side of port 0)
 *     become `0x1D..` (PHY 29 = copper-side of port 1).
 *   - All `0x12..` MDIO encoded addresses (PHY 18 = SGMII-side of port 0)
 *     become `0x13..` (PHY 19 = SGMII-side of port 1).
 *   - MAC register writes for CoreTSE_1 go to TSE1_BASEADDR (0x60003000)
 *     instead of TSE_BASEADDR (0x60000000).
 * MDIO transactions still go through CoreTSE_0's MDIO master (TSE_BASEADDR
 * for the MDIO command/status registers) because that's the only MDIO master
 * physically wired to the VSC8575. The encoded PHY address routes within the
 * chip.
 *
 * Port-1 PHY addresses (29 and 19) are best-guess by +1 analogy with port 0.
 * The MDIO scan at boot will confirm. If addresses differ, edit the four
 * `PHY1_*` defines below and reflash.
 *
 * Defensive change in port-1 functions only: the AN4623 polling loops are
 * unbounded `while(1)`; in port-1 versions they have a bounded timeout so
 * a missing/unresponsive PHY logs an error instead of hanging the CPU.
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
 * Port-1 mapping. CoreTSE_1 sits at CoreAPB3 slot 3.
 * Slot stride is 0x1000 starting at 0x60000000 (slot 0 = CoreTSE_0,
 * slot 1 = UART, slot 2 = SPI, slot 3 = CoreTSE_1).
 */
#define TSE1_BASEADDR       0x60003000UL

/* MDIO addresses for the two halves of each port's PHY block on the VSC8575.
 * Port 0 values verified in the AN4623 firmware. Port 1 values are +1
 * by analogy; MDIO scan will confirm. */
#define PHY0_COPPER_ADDR    28      /* encodes as 0x1C in MDIO command */
#define PHY0_SGMII_ADDR     18      /* encodes as 0x12 */
#define PHY1_COPPER_ADDR    29      /* encodes as 0x1D — GUESSED */
#define PHY1_SGMII_ADDR     19      /* encodes as 0x13 — GUESSED */

#define MDIO_POLL_TIMEOUT_LOOPS   2000000u   /* ~few seconds at 80 MHz */

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

static void uart_print_hex32(uint32_t v)
{
    uart_print_hex16((uint16_t)(v >> 16));
    uart_print_hex16((uint16_t)v);
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

static void mdio_scan(uint32_t tse_base)
{
    uart_print("[scan] sweeping MDIO 0..31 via TSE @ ");
    uart_print_hex32(tse_base);
    uart_print("\r\n");
    for (uint8_t addr = 0; addr < 32; addr++) {
        uint16_t id1 = mdio_read(tse_base, addr, 2);
        uint16_t id2 = mdio_read(tse_base, addr, 3);
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

/*--------------------------- Status dump helper -----------------------------*/

static void dump_phy_status(uint32_t tse_base, uint8_t phy_addr, const char *label)
{
    uint16_t st = mdio_read(tse_base, phy_addr, 1);
    uart_print("[state] ");
    uart_print(label);
    uart_print(" PHY ");
    uart_print_dec(phy_addr);
    uart_print(" status=");
    uart_print_hex16(st);
    uart_print(" link=");
    uart_print_dec((st >> 2) & 1);
    uart_print(" aneg_done=");
    uart_print_dec((st >> 5) & 1);
    uart_print("\r\n");
}

/*======================================================================*/
/* PORT 0 INIT — unchanged from AN4623 / iteration 1.                   */
/* These functions are KNOWN to work. They drive PHY 28 (copper) and    */
/* PHY 18 (SGMII), with MAC at TSE_BASEADDR.                            */
/*======================================================================*/

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

/*======================================================================*/
/* PORT 1 INIT — mirror of port 0 with PHY/base address constants       */
/* changed. ALL MDIO transactions still issued via TSE_BASEADDR because */
/* CoreTSE_0 owns the (only) MDIO master. PHY targets are 29 (copper)   */
/* and 19 (SGMII). MAC writes go to TSE1_BASEADDR.                      */
/*======================================================================*/

void Phy1_advertise(void)
{
  uint32_t phy_reg = 0xFFFF;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D04;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg &= ~(0x1E);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D04;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D09;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg |= 0x200;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D09;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);
}

void phy1_autonegotiation(void)
{
  uint32_t phy_reg = 0xFFFF;
  uint16_t autoneg_complete;
  volatile uint32_t copper_aneg_timeout = 1000000u;
  volatile uint32_t sgmii_aneg_timeout = 100000u;
  uint8_t copper_link_up;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg |= 0x1200;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  do {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D01;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    autoneg_complete = phy_reg & 0x0020u;
    --copper_aneg_timeout;
  } while(!autoneg_complete && (copper_aneg_timeout != 0u));

  for (volatile uint32_t i = 0; i < 100000; i++);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D01;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  copper_link_up = phy_reg & 0x0004;

  if(copper_link_up != 0u)
  {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1300;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    phy_reg |= 0x1000;

    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1300;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1300;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    phy_reg |= 0x0200;

    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1300;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    do {
      *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1301;
      *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
      while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

      phy_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
      *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

      autoneg_complete = phy_reg & 0x0020;
      --sgmii_aneg_timeout;
    } while((!autoneg_complete) && (sgmii_aneg_timeout != 0u));
  }
}

void phy1_init (void)
{
  volatile uint16_t phy_reg_0;
  volatile uint16_t temp;
  volatile uint16_t id1=0, id2=0, phy_mac_reg = 0;
  uint32_t timeout;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D02;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  id1 = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D03;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  id2 = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  /* Quick sanity check: if PHY 29 doesn't respond (ID register all-ones
   * or all-zeros), skip the rest of this function — we'd just hang in
   * the polling loops below. */
  if (id1 == 0xFFFF || (id1 == 0x0000 && id2 == 0x0000)) {
    uart_print("[phy1] WARNING: PHY 29 ID register reads as ");
    uart_print_hex16(id1);
    uart_print(" / ");
    uart_print_hex16(id2);
    uart_print(" — PHY likely absent, skipping phy1_init\r\n");
    return;
  }

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0003;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D10;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_mac_reg = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_mac_reg |= 0x80;

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D10;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_mac_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0010;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_mac_reg = 0x80F0;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D12;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_mac_reg;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  /* Poll for command-complete with bounded timeout. AN4623's port-0
   * version uses while(1); we add a counter so an unresponsive PHY
   * doesn't hang the CPU. */
  timeout = MDIO_POLL_TIMEOUT_LOOPS;
  while(timeout-- > 0)
  {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D12;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    temp = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

    if((temp & 0x8000) == 0)
    {
      break;
    }
  }
  if (timeout == 0) {
    uart_print("[phy1] WARNING: timeout waiting for PHY 29 reg 0x12 bit 15 clear\r\n");
  }

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D1F;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = 0x0;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  phy_reg_0 = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  phy_reg_0 = phy_reg_0 | 0x8000;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x02C) = phy_reg_0;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  /* Bounded version of the PHY-reset wait. */
  timeout = MDIO_POLL_TIMEOUT_LOOPS;
  while(timeout-- > 0)
  {
    *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D00;
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
    while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

    temp = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
    *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;
    if((temp & 0x8000) == 0)
    {
      break;
    }
  }
  if (timeout == 0) {
    uart_print("[phy1] WARNING: timeout waiting for PHY 29 reset complete\r\n");
  }

  *(volatile unsigned int *) (TSE_BASEADDR + 0x028) = 0x1D00;
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x1;
  while ((*(volatile unsigned int *) (TSE_BASEADDR + 0x034)) != 0);

  temp = *(volatile unsigned int *) (TSE_BASEADDR + 0x030);
  *(volatile unsigned int *) (TSE_BASEADDR + 0x024) = 0x0;

  (void)id1; (void)id2; (void)temp;
}

void tse1_init (void)
{
  uint32_t tse_reg = 0xFFFF;

  /* Same MAC register sequence as tse_init(), targeting TSE1_BASEADDR.
   * Values copied verbatim — same operating mode, same address filter
   * defaults, same MDIO clock prescaler. The MDIO clock register write
   * here configures CoreTSE_1's MDIO master, but its MDIO pins are not
   * wired in the SmartDesign (marked unused in top.tcl), so the master
   * is harmless dead weight. */
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x000) = 0x00000005;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x004) = 0x00007201;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x040) = 0x6060603C;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x044) = 0xB1C00000;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x048) = 0x0000FF00;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x04C) = 0x0FFF0000;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x050) = 0x04000180;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x054) = 0x0680FFFF;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x058) = 0x00000000;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x05C) = 0x0007FFFF;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x1C0) = 0x0000000F;
  *(volatile unsigned int *) (TSE1_BASEADDR + 0x020) = 0x0007;

  tse_reg = *(volatile unsigned int *) (TSE1_BASEADDR + 0x20);
  (void)tse_reg;

  phy1_init();
}

/*-------------------------- main ------------------------------------------*/

int main(void)
{
    UART_init(&g_uart, COREUARTAPB0_BASE_ADDR,
              BAUD_VALUE_115200, (DATA_8_BITS | NO_PARITY));
    uart_print("\r\n\r\n[boot] interlock firmware iter-2 starting\r\n");

    uart_print("[boot] configure_zl30364 (clock generator)\r\n");
    configure_zl30364();
    uart_print("[boot] configure_zl30364 done\r\n");

    uart_print("[boot] tse_init (MAC 0 @ ");
    uart_print_hex32(TSE_BASEADDR);
    uart_print(", PHY 28 copper / 18 SGMII)\r\n");
    tse_init();
    uart_print("[boot] tse_init done\r\n");

    /* Scan now that CoreTSE_0's MDIO master is configured but port-1's PHYs
     * haven't been touched yet — gives us a clean picture of what's on the bus. */
    mdio_scan(TSE_BASEADDR);

    uart_print("[boot] tse1_init (MAC 1 @ ");
    uart_print_hex32(TSE1_BASEADDR);
    uart_print(", PHY 29 copper / 19 SGMII)\r\n");
    tse1_init();
    uart_print("[boot] tse1_init done\r\n");

    uart_print("[boot] Phy_advertise (port 0, PHY 28)\r\n");
    Phy_advertise();
    uart_print("[boot] Phy_advertise done\r\n");

    uart_print("[boot] Phy1_advertise (port 1, PHY 29)\r\n");
    Phy1_advertise();
    uart_print("[boot] Phy1_advertise done\r\n");

    uart_print("[boot] phy_autonegotiation (port 0)\r\n");
    phy_autonegotiation();
    uart_print("[boot] phy_autonegotiation done\r\n");

    uart_print("[boot] phy1_autonegotiation (port 1)\r\n");
    phy1_autonegotiation();
    uart_print("[boot] phy1_autonegotiation done\r\n");

    /* Final state dump. */
    dump_phy_status(TSE_BASEADDR, PHY0_COPPER_ADDR, "port0 copper");
    dump_phy_status(TSE_BASEADDR, PHY0_SGMII_ADDR,  "port0 SGMII");
    dump_phy_status(TSE_BASEADDR, PHY1_COPPER_ADDR, "port1 copper");
    dump_phy_status(TSE_BASEADDR, PHY1_SGMII_ADDR,  "port1 SGMII");

    /* CoreTSE_1 sanity probe (already initialized, this just confirms the
     * address is readable and what MAC_CONFIG_1 reads back as). */
    uart_print("[probe] CoreTSE_1 MAC_CONFIG_1 reads ");
    uint32_t tse1_mc1 = *(volatile unsigned int *)(TSE1_BASEADDR + 0x000);
    uart_print_hex32(tse1_mc1);
    uart_print("\r\n");

    uart_print("[boot] init complete — polling both ports\r\n");

    uint32_t tick = 0;
    while (1) {
        for (volatile uint32_t i = 0; i < 8000000; i++) { }
        uint16_t s0c = mdio_read(TSE_BASEADDR, PHY0_COPPER_ADDR, 1);
        uint16_t s0s = mdio_read(TSE_BASEADDR, PHY0_SGMII_ADDR,  1);
        uint16_t s1c = mdio_read(TSE_BASEADDR, PHY1_COPPER_ADDR, 1);
        uint16_t s1s = mdio_read(TSE_BASEADDR, PHY1_SGMII_ADDR,  1);
        uart_print("[poll t=");
        uart_print_dec(tick++);
        uart_print("] p0c=");
        uart_print_hex16(s0c);
        uart_print(" p0s=");
        uart_print_hex16(s0s);
        uart_print(" p1c=");
        uart_print_hex16(s1c);
        uart_print(" p1s=");
        uart_print_hex16(s1s);
        uart_print(" (link bits: ");
        uart_print_dec((s0c >> 2) & 1);
        uart_print_dec((s0s >> 2) & 1);
        uart_print_dec((s1c >> 2) & 1);
        uart_print_dec((s1s >> 2) & 1);
        uart_print(")\r\n");
    }
}
