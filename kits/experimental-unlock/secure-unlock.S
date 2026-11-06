adr x2, result
str x19, [x2, #0xc0]
str x20, [x2, #0xc8]
mov x19, x2
mov x20, x30
mov w3, #0x4e4f
movk w3, #0x3432, lsl #16
str w3, [x2]
mov w3, #1
str w3, [x2, #4]
str x18, [x2, #8]
str x30, [x2, #0x10]
mov x3, sp
str x3, [x2, #0x18]
mrs x3, CurrentEL
str x3, [x2, #0x20]
mrs x3, SCTLR_EL2
str x3, [x2, #0x28]
mrs x3, DAIF
str x3, [x2, #0x30]
mrs x3, PAR_EL1
str x3, [x2, #0x58]
mov w3, #-1
str w3, [x2, #0x60]
str w3, [x2, #0x64]
str w3, [x2, #0x80]
str w3, [x2, #0x84]
str w3, [x2, #0x88]
str w3, [x2, #0x90]
str w3, [x2, #0x94]
str w3, [x2, #0x98]
str w3, [x2, #0x9c]
str w3, [x2, #0xa0]
str w3, [x2, #0xa4]
str wzr, [x2, #0x68]
str wzr, [x2, #0x6c]
str wzr, [x2, #0xa8]
str wzr, [x2, #0xac]
mov x3, #21952
movk x3, #47456, lsl #16
cmp x18, x3
b.ne context_failure
mov x3, #10280
movk x3, #48998, lsl #16
cmp x30, x3
b.ne context_failure
ldr x3, [x2, #0x20]
cmp x3, #8
b.ne context_failure
ldr x3, [x2, #0x18]
tst x3, #15
b.ne context_failure
ldr x3, [x2, #0x28]
tbz x3, #0, context_failure
ldr x3, [x18, #0x70]
str x3, [x2, #0x38]
mov x4, #24576
movk x4, #48993, lsl #16
cmp x3, x4
b.ne context_failure
mov x4, #7460
movk x4, #48994, lsl #16
str x4, [x2, #64]
mov x4, #48328
movk x4, #48996, lsl #16
str x4, [x2, #72]
mov x4, #756
movk x4, #48999, lsl #16
str x4, [x2, #80]
mov x4, #7460
movk x4, #48994, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #384]
mov w5, #31741
movk w5, #43452, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #388]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #392]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #396]
mov w5, #2932
movk w5, #53248, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #48328
movk x4, #48996, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #416]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #420]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #424]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #428]
mov w5, #2612
movk w5, #36864, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #756
movk x4, #48999, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #448]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #452]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #456]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #460]
mov w5, #17315
movk w5, #37121, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #6112
movk x4, #48994, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #480]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #484]
mov w5, #514
movk w5, #53888, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #488]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #492]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #13720
movk x4, #49004, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #512]
mov w5, #4
movk w5, #63808, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #516]
mov w5, #13444
movk w5, #63808, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #520]
mov w5, #3204
movk w5, #63808, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #524]
mov w5, #128
movk w5, #54815, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #13704
movk x4, #49004, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #544]
mov w5, #2
movk w5, #63808, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #548]
mov w5, #13378
movk w5, #63808, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #552]
mov w5, #2114
movk w5, #63808, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #556]
mov w5, #64
movk w5, #54815, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #6424
movk x4, #48994, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #576]
mov w5, #31741
movk w5, #43449, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #580]
mov w5, #1026
movk w5, #53888, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #584]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #588]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #57080
movk x4, #49008, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #608]
mov w5, #36634
movk w5, #575, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #612]
mov w5, #10538
movk w5, #17195, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #616]
mov w5, #50319
movk w5, #34014, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #620]
mov w5, #13681
movk w5, #26496, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #57112
movk x4, #49008, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #640]
mov w5, #36634
movk w5, #575, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #644]
mov w5, #10538
movk w5, #17195, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #648]
mov w5, #50319
movk w5, #34014, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #652]
mov w5, #13681
movk w5, #26496, lsl #16
cmp w6, w5
b.ne prefix_failure
mov w3, #1
str w3, [x2, #0x68]
add x0, x2, #0x64
mov x4, #7460
movk x4, #48994, lsl #16
blr x4
mov x2, x19
mov x30, x20
str w0, [x2, #0x60]
cmp w0, #1
b.ne read_before_failure
ldr w3, [x2, #0x64]
cbz w3, already_unlocked
cmp w3, #1
b.ne read_before_failure
mov w3, #1
str w3, [x2, #0xac]
mov x4, #6112
movk x4, #48994, lsl #16
blr x4
mov x2, x19
mov x30, x20
str w0, [x2, #0x80]
mov x4, #28784
movk x4, #49019, lsl #16
ldr x3, [x4, #0]
str x3, [x2, #304]
ldr x3, [x4, #8]
str x3, [x2, #312]
ldr x3, [x4, #16]
str x3, [x2, #320]
ldr x3, [x4, #24]
str x3, [x2, #328]
ldr x3, [x4, #32]
str x3, [x2, #336]
ldr x3, [x4, #40]
str x3, [x2, #344]
ldr w3, [x4, #0x28]
str w3, [x2, #0x84]
ldr w3, [x4, #0x2c]
str w3, [x2, #0x88]
ldr w3, [x4, #0x24]
str w3, [x2, #0x8c]
mov x4, #28776
movk x4, #49019, lsl #16
ldr x3, [x4]
str x3, [x2, #0xb0]
ldr w3, [x2, #0x80]
cmp w3, #1
b.ne open_failure
ldr w3, [x2, #0x84]
cbnz w3, open_failure
ldr x0, [x2, #0xb0]
cbz x0, open_failure
mov w3, #3
str w3, [x2, #0x100]
ldr w3, [x2, #0x8c]
str w3, [x2, #0x104]
str xzr, [x2, #0x108]
mov x3, #1
str x3, [x2, #0x110]
str xzr, [x2, #0x118]
str xzr, [x2, #0x120]
str xzr, [x2, #0x128]
str w3, [x2, #0x6c]
add x1, x2, #0x100
add x3, x2, #0x110
mov w2, #1
mov x4, #13720
movk x4, #49004, lsl #16
blr x4
mov x2, x19
mov x30, x20
str w0, [x2, #0x90]
ldr w3, [x2, #0x108]
str w3, [x2, #0x94]
ldr w3, [x2, #0x10c]
str w3, [x2, #0x98]
ldr x0, [x2, #0xb0]
ldr w1, [x2, #0x8c]
mov x4, #13704
movk x4, #49004, lsl #16
blr x4
mov x2, x19
mov x30, x20
str w0, [x2, #0x9c]
mov w3, #2
str w3, [x2, #0x68]
add x0, x2, #0xa4
mov x4, #7460
movk x4, #48994, lsl #16
blr x4
mov x2, x19
mov x30, x20
str w0, [x2, #0xa0]
mov x3, sp
str x3, [x2, #0x70]
str x18, [x2, #0x78]
ldr x4, [x2, #0x18]
cmp x3, x4
b.ne post_failure
ldr x4, [x2, #8]
cmp x18, x4
b.ne post_failure
mrs x3, SCTLR_EL2
str x3, [x2, #0xf0]
ldr x4, [x2, #0x28]
cmp x3, x4
b.ne post_failure
mov x4, #7460
movk x4, #48994, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #400]
mov w5, #31741
movk w5, #43452, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #404]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #408]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #412]
mov w5, #2932
movk w5, #53248, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #48328
movk x4, #48996, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #432]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #436]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #440]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #444]
mov w5, #2612
movk w5, #36864, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #756
movk x4, #48999, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #464]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #468]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #472]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #476]
mov w5, #17315
movk w5, #37121, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #6112
movk x4, #48994, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #496]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #500]
mov w5, #514
movk w5, #53888, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #504]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #508]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #13720
movk x4, #49004, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #528]
mov w5, #4
movk w5, #63808, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #532]
mov w5, #13444
movk w5, #63808, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #536]
mov w5, #3204
movk w5, #63808, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #540]
mov w5, #128
movk w5, #54815, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #13704
movk x4, #49004, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #560]
mov w5, #2
movk w5, #63808, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #564]
mov w5, #13378
movk w5, #63808, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #568]
mov w5, #2114
movk w5, #63808, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #572]
mov w5, #64
movk w5, #54815, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #6424
movk x4, #48994, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #592]
mov w5, #31741
movk w5, #43449, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #596]
mov w5, #1026
movk w5, #53888, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #600]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #604]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #57080
movk x4, #49008, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #624]
mov w5, #36634
movk w5, #575, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #628]
mov w5, #10538
movk w5, #17195, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #632]
mov w5, #50319
movk w5, #34014, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #636]
mov w5, #13681
movk w5, #26496, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #57112
movk x4, #49008, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #656]
mov w5, #36634
movk w5, #575, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #660]
mov w5, #10538
movk w5, #17195, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #664]
mov w5, #50319
movk w5, #34014, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #668]
mov w5, #13681
movk w5, #26496, lsl #16
cmp w6, w5
b.ne post_failure
mov w3, #1
str w3, [x2, #0xa8]
ldr w3, [x2, #0xa0]
cmp w3, #1
b.ne read_after_failure
ldr w3, [x2, #0xa4]
cmp w3, #1
b.hi read_after_failure
ldr w4, [x2, #0x90]
ldr w5, [x2, #0x94]
orr w4, w4, w5
cbnz w4, write_error
cbnz w3, still_locked
mov w3, #2
b finish
write_error:
cbz w3, ambiguous_change
mov w3, #8
b finish
context_failure:
mov w3, #3
b finish
read_before_failure:
mov w3, #4
b finish
post_failure:
mov w3, #5
b finish
already_unlocked:
mov w3, #6
b finish
open_failure:
mov w3, #7
b finish
prefix_failure:
mov w3, #9
b finish
still_locked:
mov w3, #10
b finish
read_after_failure:
mov w3, #11
b finish
ambiguous_change:
mov w3, #12
finish:
str w3, [x2, #4]
ldr x3, [x2, #0x58]
msr PAR_EL1, x3
ldr x18, [x2, #8]
ldr x3, [x2, #0x18]
mov sp, x3
mov x30, x20
ldr x19, [x2, #0xc0]
ldr x20, [x2, #0xc8]
mov w0, #0
ret
.org 0x1000
result:
