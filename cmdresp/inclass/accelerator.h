#ifndef CMDRESP_ACCELERATOR_H
#define CMDRESP_ACCELERATOR_H
#include "streamutils_hls.h"
using AxisWord = streamutils::axi4s_word<32>;
void accelerator(hls::stream<AxisWord>& in_stream,
                 hls::stream<AxisWord>& out_stream,
                 volatile unsigned& halted, volatile unsigned& error,
                 volatile unsigned& tx_id, volatile unsigned& consumed);
#endif
