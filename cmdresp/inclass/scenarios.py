"""Deterministic activations, including independently specified error expectations."""
import numpy as np
from design import MODE
from model import CONFIG,DATA,END,Error,beat,header,command,fbits,run


def make_scenarios():
    cases = []
    def add(name, words, want_error=0, want_tx=0, want_consumed=None, recovery_for=None):
        expected = run(words)
        assert expected["error"] == int(want_error), (name, expected)
        assert expected["tx_id"] == want_tx, (name, expected)
        assert expected["consumed"] == (len(words) if want_consumed is None else want_consumed)
        assert not expected["output"] or expected["output"][-1][1] == 1
        cases.append(dict(name=name, input=words, expected=expected,recovery_for=recovery_for))

    cfg = [16384,16384] if MODE == "fir" else [fbits(2),fbits(-1)]
    xs = [8192,16384,-8192] if MODE == "fir" else [fbits(-2),fbits(0),fbits(3)]
    good = command(CONFIG,10,cfg)+command(DATA,11,xs)+header(END,12,0)
    add("basic_hand", good)
    add("end_only", header(END,0,0))
    add("multiple_data_repeated_tx", command(CONFIG,0xffffffff,cfg)+
        command(DATA,7,xs[:1])+command(DATA,7,xs[1:])+header(END,7,0))
    newcfg = [32767] if MODE == "fir" else [fbits(-.5),fbits(2)]
    add("reconfigure_reset", command(CONFIG,1,cfg)+command(DATA,2,xs)+
        command(CONFIG,3,newcfg)+command(DATA,4,xs)+header(END,5,0))
    rng = np.random.default_rng(5005)
    for i in range(6):
        if MODE == "fir":
            h = rng.integers(-32768,32768,1+i).tolist()
            x = rng.integers(-32768,32768,17+i*11).tolist()
        else:
            h = [fbits(v) for v in rng.uniform(-2,2,2)]
            x = [fbits(v) for v in rng.uniform(-4,4,17+i*11)]
        add(f"random_{i}",command(CONFIG,100+i,h)+command(DATA,200+i,x)+header(END,300+i,0))
    if MODE == "fir":
        specials = [
            ("ties_even",[16384],[1,3,5,-1,-3,-5]),
            ("saturation_both",[-32768,-32768],[-32768,-32768,32767,32767]),
            ("nontie_rounding",[10923],[1,2,4,-1,-2,-4]),
            ("zero_coefficients",[0]*8,[-32768,32767,0,1]),
            ("impulse_eight_taps",[1000,-2000,3000,-4000,5000,-6000,7000,-8000],
             [16384]+[0]*15),
            ("minimum_sizes",[-32768],[-32768]),
            ("maximum_sizes",[32767,-32768,20000,-20000,10000,-10000,1,-1],
             rng.integers(-32768,32768,1024).tolist())]
    else:
        specials = [("separate_rounding",[fbits(1+2**-23),fbits(-1)],[fbits(1-2**-23)]),
                    ("minimum_sizes",[fbits(-1),fbits(2)],[fbits(0)]),
                    ("maximum_sizes",cfg,[fbits(v) for v in rng.uniform(-4,4,1024)])]
    for name,h,x in specials:
        add(name,command(CONFIG,20,h)+command(DATA,21,x)+header(END,22,0))

    def error(name, words, code, tx=77, consumed=None):
        add(name,words,code,tx,consumed)
        add("recover_"+name,good,recovery_for=name)

    # All errors except DATA-before-CONFIG follow a fully emitted good response.
    prefix = command(CONFIG,1,cfg)+command(DATA,2,xs)
    npre = len(prefix)
    error("unconfigured",header(DATA,77,1),Error.UNCONFIGURED)
    error("header_early_before_tx",prefix+[beat(999,True)],Error.HEADER_EARLY,0)
    error("header_early_after_tx",prefix+[beat(DATA),beat(77,True)],Error.HEADER_EARLY)
    error("header_missing",prefix+[beat(DATA),beat(77),beat(1)],Error.HEADER_MISSING)
    error("unknown_command",prefix+header(0xffffffff,77,0),Error.UNKNOWN_COMMAND)
    for cmd,n,name in [(CONFIG,0,"config_zero"),(CONFIG,9 if MODE=="fir" else 3,"config_too_large"),
                       (DATA,0,"data_zero"),(DATA,1025,"data_too_large"),(END,1,"end_nonzero")]:
        error(name,prefix+header(cmd,77,n),Error.INVALID_COUNT)
    if MODE != "fir":
        error("config_too_small",prefix+header(CONFIG,77,1),Error.INVALID_COUNT)
    error("config_early",prefix+header(CONFIG,77,2)+[beat(cfg[0],True)],Error.CONFIG_EARLY)
    error("config_missing",prefix+header(CONFIG,77,2)+[beat(cfg[0]),beat(cfg[1])],Error.CONFIG_MISSING)
    error("data_early",prefix+header(DATA,77,3)+[beat(xs[0],True)],Error.DATA_EARLY)
    error("data_missing",prefix+header(DATA,77,1)+[beat(xs[0])],Error.DATA_MISSING)
    for loc in ("header","config","data"):
        for channel in ("keep","strb"):
            maskword = beat(DATA if loc=="header" else xs[0],True,
                            7 if channel=="keep" else 15,7 if channel=="strb" else 15)
            body = [maskword] if loc=="header" else header(CONFIG if loc=="config" else DATA,77,1)+[maskword]
            if loc=="config" and MODE!="fir":
                body = header(CONFIG,77,2)+[maskword]
            error(f"mask_{loc}_{channel}",prefix+body,Error.BYTE_MASK,0 if loc=="header" else 77)
    if MODE == "fir":
        for cmd,location in [(CONFIG,"tap"),(DATA,"sample")]:
            for val,name in [(0x00008000,"negative_not_extended"),(0xffff0001,"positive_bad_extension")]:
                error(location+"_"+name,prefix+header(cmd,77,1)+[beat(val,True)],Error.NONCANONICAL_Q15)
        error("framing_precedes_value",prefix+header(DATA,77,2)+[beat(0x00008000,True)],Error.DATA_EARLY)
    error("mask_precedes_framing",prefix+[beat(DATA,True,0,15)],Error.BYTE_MASK,0)
    error("framing_precedes_opcode",prefix+[beat(999),beat(77),beat(0)],Error.HEADER_MISSING)
    error("opcode_precedes_count",prefix+header(999,77,9999),Error.UNKNOWN_COMMAND)
    error("count_precedes_state",header(DATA,77,0),Error.INVALID_COUNT)
    # Queued suffix proves no draining in C; consumed status also checks RTL.
    suffix = header(END,123,0)+[beat(0xfeedface,True)]
    error("queued_suffix_not_consumed",prefix+header(DATA,77,1)+[beat(xs[0])]+suffix,
          Error.DATA_MISSING,consumed=npre+4)
    return cases
