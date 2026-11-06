adr x2, result
str x19, [x2, #0xc0]
str x20, [x2, #0xc8]
mov x19, x2
mov x20, x30
mov w3, #0x4e4f
movk w3, #0x3332, lsl #16
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
str wzr, [x2, #0x68]
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
str w6, [x2, #128]
mov w5, #31741
movk w5, #43452, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #132]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #136]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #140]
mov w5, #2932
movk w5, #53248, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #48328
movk x4, #48996, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #160]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #164]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #168]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #172]
mov w5, #2612
movk w5, #36864, lsl #16
cmp w6, w5
b.ne prefix_failure
mov x4, #756
movk x4, #48999, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #208]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #4]
str w6, [x2, #212]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #8]
str w6, [x2, #216]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne prefix_failure
ldr w6, [x4, #12]
str w6, [x2, #220]
mov w5, #17315
movk w5, #37121, lsl #16
cmp w6, w5
b.ne prefix_failure
mov w3, #1
str w3, [x2, #0x68]
add x0, x2, #0x64
ldr x4, [x2, #0x40]
blr x4
mov x2, x19
mov x30, x20
str w0, [x2, #0x60]
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
str w6, [x2, #144]
mov w5, #31741
movk w5, #43452, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #148]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #152]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #156]
mov w5, #2932
movk w5, #53248, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #48328
movk x4, #48996, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #176]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #180]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #184]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #188]
mov w5, #2612
movk w5, #36864, lsl #16
cmp w6, w5
b.ne post_failure
mov x4, #756
movk x4, #48999, lsl #16
ldr w6, [x4, #0]
str w6, [x2, #224]
mov w5, #31741
movk w5, #43451, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #4]
str w6, [x2, #228]
mov w5, #1021
movk w5, #37120, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #8]
str w6, [x2, #232]
mov w5, #21491
movk w5, #43265, lsl #16
cmp w6, w5
b.ne post_failure
ldr w6, [x4, #12]
str w6, [x2, #236]
mov w5, #17315
movk w5, #37121, lsl #16
cmp w6, w5
b.ne post_failure
ldr w0, [x2, #0x60]
cmp w0, #1
b.ne read_failure
ldr w0, [x2, #0x64]
cmp w0, #1
b.hi read_failure
mov w3, #2
b finish
context_failure:
mov w3, #3
b finish
read_failure:
mov w3, #4
b finish
post_failure:
mov w3, #5
b finish
prefix_failure:
mov w3, #9
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
.org 0x600
result:
