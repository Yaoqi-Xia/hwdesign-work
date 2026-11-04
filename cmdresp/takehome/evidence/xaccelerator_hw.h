// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
// Tool Version Limit: 2026.06
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
// control
// 0x00 : Control signals
//        bit 0  - ap_start (Read/Write/COH)
//        bit 1  - ap_done (Read/COR)
//        bit 2  - ap_idle (Read)
//        bit 3  - ap_ready (Read/COR)
//        bit 7  - auto_restart (Read/Write)
//        bit 9  - interrupt (Read)
//        others - reserved
// 0x04 : Global Interrupt Enable Register
//        bit 0  - Global Interrupt Enable (Read/Write)
//        others - reserved
// 0x08 : IP Interrupt Enable Register (Read/Write)
//        bit 0 - enable ap_done interrupt (Read/Write)
//        bit 1 - enable ap_ready interrupt (Read/Write)
//        others - reserved
// 0x0c : IP Interrupt Status Register (Read/TOW)
//        bit 0 - ap_done (Read/TOW)
//        bit 1 - ap_ready (Read/TOW)
//        others - reserved
// 0x10 : Data signal of halted
//        bit 31~0 - halted[31:0] (Read)
// 0x14 : Control signal of halted
//        bit 0  - halted_ap_vld (Read/COR)
//        others - reserved
// 0x20 : Data signal of error
//        bit 31~0 - error[31:0] (Read)
// 0x24 : Control signal of error
//        bit 0  - error_ap_vld (Read/COR)
//        others - reserved
// 0x30 : Data signal of tx_id
//        bit 31~0 - tx_id[31:0] (Read)
// 0x34 : Control signal of tx_id
//        bit 0  - tx_id_ap_vld (Read/COR)
//        others - reserved
// 0x40 : Data signal of consumed
//        bit 31~0 - consumed[31:0] (Read)
// 0x44 : Control signal of consumed
//        bit 0  - consumed_ap_vld (Read/COR)
//        others - reserved
// (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

#define XACCELERATOR_CONTROL_ADDR_AP_CTRL       0x00
#define XACCELERATOR_CONTROL_ADDR_GIE           0x04
#define XACCELERATOR_CONTROL_ADDR_IER           0x08
#define XACCELERATOR_CONTROL_ADDR_ISR           0x0c
#define XACCELERATOR_CONTROL_ADDR_HALTED_DATA   0x10
#define XACCELERATOR_CONTROL_BITS_HALTED_DATA   32
#define XACCELERATOR_CONTROL_ADDR_HALTED_CTRL   0x14
#define XACCELERATOR_CONTROL_ADDR_ERROR_DATA    0x20
#define XACCELERATOR_CONTROL_BITS_ERROR_DATA    32
#define XACCELERATOR_CONTROL_ADDR_ERROR_CTRL    0x24
#define XACCELERATOR_CONTROL_ADDR_TX_ID_DATA    0x30
#define XACCELERATOR_CONTROL_BITS_TX_ID_DATA    32
#define XACCELERATOR_CONTROL_ADDR_TX_ID_CTRL    0x34
#define XACCELERATOR_CONTROL_ADDR_CONSUMED_DATA 0x40
#define XACCELERATOR_CONTROL_BITS_CONSUMED_DATA 32
#define XACCELERATOR_CONTROL_ADDR_CONSUMED_CTRL 0x44

