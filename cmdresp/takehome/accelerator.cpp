#include "accelerator.h"
#include "design.h"
#include "include/resp_hdr.h"

namespace {
enum { CONFIG=1, DATA=2, END=3 };
enum { OK=0, HEADER_EARLY=1, HEADER_MISSING=2, UNKNOWN_COMMAND=3,
       INVALID_COUNT=4, UNCONFIGURED=5, CONFIG_EARLY=6, CONFIG_MISSING=7,
       DATA_EARLY=8, DATA_MISSING=9, BYTE_MASK=10, NONCANONICAL_Q15=11 };

unsigned check(const AxisWord& w, unsigned i, unsigned n,
               unsigned early, unsigned missing, bool numeric) {
#pragma HLS INLINE
    if (w.keep != 15 || w.strb != 15) return BYTE_MASK;
    if (w.last && i != n-1) return early;
    if (!w.last && i == n-1) return missing;
#if DESIGN_FIR
    ap_int<16> raw = w.data.range(15,0);
    ap_int<32> extended = raw;
    if (numeric && extended != w.data) return NONCANONICAL_Q15;
#endif
    return OK;
}

void respond(hls::stream<AxisWord>& out, unsigned cmd, unsigned tx, unsigned n) {
#pragma HLS INLINE
    RespHdr response;
    response.cmd_type=cmd; response.tx_id=tx; response.count=n;
    response.write_axi4_stream<32>(out,true);
}

#if DESIGN_FIR
ap_int<16> rounded_q15(ap_int<64> acc) {
#pragma HLS INLINE
    bool negative = acc < 0;
    ap_uint<64> magnitude = negative ? (ap_int<64>)(-acc) : acc;
    ap_uint<64> q = magnitude >> 15;
    ap_uint<15> rem = magnitude.range(14,0);
    if (rem > 16384 || (rem == 16384 && q[0])) ++q;
    ap_int<64> result = (ap_int<64>)q;
    if (negative) result = -result;
    if (result > 32767) return 32767;
    if (result < -32768) return -32768;
    return (ap_int<16>)result;
}
#else
float multiply(float a, float x) {
#pragma HLS INLINE off
    return a*x;
}
float add_offset(float product, float b) {
#pragma HLS INLINE off
    return product+b;
}
#endif

unsigned execute(hls::stream<AxisWord>& in_stream,
                 hls::stream<AxisWord>& out_stream,
                 unsigned& tx, unsigned& count_read) {
    bool configured = false;
    unsigned ntaps = 0;
    unsigned result[1024];
#if DESIGN_FIR
    ap_int<16> taps[8], history[8];
#pragma HLS ARRAY_PARTITION variable=taps complete
#pragma HLS ARRAY_PARTITION variable=history complete
    for (int k=0;k<8;++k) {
#pragma HLS UNROLL
        taps[k]=0; history[k]=0;
    }
#else
    float a=0.0f, b=0.0f;
#endif
COMMANDS:
    while (true) {
        unsigned h[3];
#pragma HLS ARRAY_PARTITION variable=h complete
        tx=0;
READ_HEADER:
        for (unsigned j=0;j<3;++j) {
            AxisWord w=in_stream.read(); ++count_read;
            if (j==1) tx=w.data.to_uint();
            unsigned e=check(w,j,3,HEADER_EARLY,HEADER_MISSING,false);
            if (e) return e;
            h[j]=w.data.to_uint();
        }
        unsigned cmd=h[0], n=h[2];
        if (cmd!=CONFIG && cmd!=DATA && cmd!=END) return UNKNOWN_COMMAND;
#if DESIGN_FIR
        bool bad_config = n<1 || n>8;
#else
        bool bad_config = n!=2;
#endif
        if ((cmd==CONFIG && bad_config) || (cmd==DATA && (n<1 || n>1024)) ||
            (cmd==END && n!=0)) return INVALID_COUNT;
        if (cmd==DATA && !configured) return UNCONFIGURED;
        if (cmd==END) { tx=0; return OK; }
        if (cmd==CONFIG) {
READ_CONFIG:
            for (unsigned j=0;j<n;++j) {
                AxisWord w=in_stream.read(); ++count_read;
                unsigned e=check(w,j,n,CONFIG_EARLY,CONFIG_MISSING,true);
                if (e) return e;
#if DESIGN_FIR
                taps[j]=w.data.range(15,0);
#else
                if (j==0) a=streamutils::uint_to_float(w.data.to_uint());
                else b=streamutils::uint_to_float(w.data.to_uint());
#endif
            }
#if DESIGN_FIR
            ntaps=n;
RESET_HISTORY:
            for (int k=0;k<8;++k) {
#pragma HLS UNROLL
                history[k]=0;
                if ((unsigned)k>=ntaps) taps[k]=0;
            }
#endif
            configured=true;
            respond(out_stream,CONFIG,tx,0);
        } else {
PROCESS_DATA:
            for (unsigned j=0;j<n;++j) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=1024
                AxisWord w=in_stream.read(); ++count_read;
                unsigned e=check(w,j,n,DATA_EARLY,DATA_MISSING,true);
                if (e) return e;
#if DESIGN_FIR
SHIFT_HISTORY:
                for (int k=7;k>0;--k) {
#pragma HLS UNROLL
                    history[k]=history[k-1];
                }
                history[0]=w.data.range(15,0);
                ap_int<64> acc=0;
DOT_PRODUCT:
                for (int k=0;k<8;++k) {
#pragma HLS UNROLL
                    ap_int<32> product=taps[k]*history[k];
                    acc+=product;
                }
                ap_int<32> y=rounded_q15(acc);
                result[j]=(ap_uint<32>)y;
#else
                float x=streamutils::uint_to_float(w.data.to_uint());
                float p=multiply(a,x);
                float y=add_offset(p,b);
                result[j]=streamutils::float_to_uint(y);
#endif
            }
            respond(out_stream,DATA,tx,n);
WRITE_RESULTS:
            for (unsigned j=0;j<n;++j) {
#pragma HLS PIPELINE II=1
                streamutils::write_axi4_word<32>(out_stream,result[j],j==n-1);
            }
        }
    }
}
} // namespace

void accelerator(hls::stream<AxisWord>& in_stream,
                 hls::stream<AxisWord>& out_stream,
                 volatile unsigned& halted, volatile unsigned& error,
                 volatile unsigned& tx_id, volatile unsigned& consumed) {
#pragma HLS INTERFACE axis port=in_stream depth=4096
#pragma HLS INTERFACE axis port=out_stream depth=4096
#pragma HLS INTERFACE s_axilite port=halted bundle=control
#pragma HLS INTERFACE s_axilite port=error bundle=control
#pragma HLS INTERFACE s_axilite port=tx_id bundle=control
#pragma HLS INTERFACE s_axilite port=consumed bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    halted=0; error=0; tx_id=0; consumed=0;
    unsigned tx=0, nr=0;
    unsigned e=execute(in_stream,out_stream,tx,nr);
    consumed=nr;
    error=e;
    tx_id=tx;
    halted=e!=OK;
}
