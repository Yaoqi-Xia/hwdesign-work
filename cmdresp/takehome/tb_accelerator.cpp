#include "accelerator.h"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

struct Beat { unsigned data,last,keep,strb; };
Beat read_beat(std::istream& f) {
    Beat b; f>>b.data>>b.last>>b.keep>>b.strb; return b;
}

int main(int argc,char** argv) {
    if (argc!=3) { std::cerr<<"usage: tb ROOT STAGE\n"; return 2; }
    std::string root=argv[1], stage=argv[2];
    std::ifstream vectors(root+"/vectors/activations.txt");
    if (!vectors) { std::cerr<<"missing vectors\n"; return 2; }
    std::ofstream actual(root+"/evidence/"+stage+"_beats.csv");
    std::ofstream status(root+"/evidence/"+stage+"_status.csv");
    actual<<"activation,beat,data,last,keep,strb\n";
    status<<"activation,scenario,halted,error,tx_id,consumed,output_beats,verdict\n";
    unsigned count; vectors>>count;
    unsigned failed=0;
    for (unsigned ci=0;ci<count;++ci) {
        unsigned id,ni,no,eh,ee,et,ec;
        std::string name;
        vectors>>id>>name>>ni>>no>>eh>>ee>>et>>ec;
        if (!vectors || id!=ci) return 2;
        hls::stream<AxisWord> in_stream("input"),out_stream("output");
        for (unsigned j=0;j<ni;++j) {
            Beat b=read_beat(vectors);
            AxisWord w; w.data=b.data; w.last=b.last; w.keep=b.keep; w.strb=b.strb;
            in_stream.write(w);
        }
        std::vector<Beat> expect;
        for (unsigned j=0;j<no;++j) expect.push_back(read_beat(vectors));
        unsigned halted=0xdeadbeef,error=0xdeadbeef,tx_id=0xdeadbeef,consumed=0xdeadbeef;
        accelerator(in_stream,out_stream,halted,error,tx_id,consumed);
        bool ok=halted==eh && error==ee && tx_id==et && consumed==ec;
        unsigned got=0,last=1;
        while (!out_stream.empty()) {
            AxisWord w=out_stream.read();
            unsigned data=(ap_uint<32>)w.data;
            actual<<ci<<','<<got<<','<<data<<','<<w.last.to_uint()<<','
                  <<w.keep.to_uint()<<','<<w.strb.to_uint()<<'\n';
            if (got>=expect.size()) ok=false;
            else {
                const Beat& e=expect[got];
                if (data!=e.data || w.last!=e.last || w.keep!=e.keep || w.strb!=e.strb) ok=false;
            }
            last=w.last.to_uint(); ++got;
        }
        if (got!=no || (got && last!=1)) ok=false;
        // Cosim's wrapper serializes the software input FIFO. The consumed
        // status is the cross-domain check; C additionally checks its remainder.
        if (stage=="csim" && in_stream.size()!=ni-ec) ok=false;
        status<<ci<<','<<name<<','<<halted<<','<<error<<','<<tx_id<<','<<consumed<<','<<got
              <<','<<(ok?"PASS":"FAIL")<<'\n';
        std::cout<<"SCENARIO "<<ci<<" "<<name<<" "<<(ok?"PASS":"FAIL")
                 <<" status="<<halted<<"/"<<error<<"/"<<tx_id
                 <<" consumed="<<consumed<<" output_beats="<<got<<'\n';
        failed+=!ok;
    }
    std::cout<<"CHECKED "<<count<<" ACTIVATIONS; FAILURES "<<failed<<'\n';
    return failed?1:0;
}
