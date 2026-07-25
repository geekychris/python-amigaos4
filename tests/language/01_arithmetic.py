"""Integer / float / bignum arithmetic on OS4 PPC."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework


def main():
    t = framework.new(__file__)

    t.section("int")
    t.check_eq(2 + 3, 5, "add")
    t.check_eq(10 - 4, 6, "sub")
    t.check_eq(7 * 6, 42, "mul")
    t.check_eq(20 // 3, 6, "floor div")
    t.check_eq(20 % 3, 2, "mod")
    t.check_eq(-7 // 2, -4, "floor div negative rounds towards -inf")
    t.check_eq(divmod(17, 5), (3, 2), "divmod")

    t.section("bignum")
    t.check_eq(2 ** 100, 1267650600228229401496703205376, "2**100")
    t.check_eq(len(str(10 ** 200)), 201, "10**200 has 201 digits")
    t.check_eq((2 ** 64) * (2 ** 64), 2 ** 128, "128-bit multiply")

    t.section("float")
    t.check(abs((0.1 + 0.2) - 0.3) < 1e-9, "0.1+0.2 close to 0.3")
    t.check_eq(round(1.234567, 3), 1.235, "round")
    t.check_eq(3.14e2, 314.0, "scientific notation")

    t.section("bitwise")
    t.check_eq(0xFF & 0x0F, 0x0F, "and")
    t.check_eq(0x30 | 0x0C, 0x3C, "or")
    t.check_eq(0xFF ^ 0x0F, 0xF0, "xor")
    t.check_eq(1 << 8, 256, "lshift")
    t.check_eq(1024 >> 2, 256, "rshift")

    t.section("comparisons")
    t.check(1 < 2 < 3, "chain <")
    t.check(not (2 == 3), "!=")
    t.check_eq(min(4, 2, 7, 1, 3), 1, "min")
    t.check_eq(max(4, 2, 7, 1, 3), 7, "max")

    t.section("math module")
    math = t.try_import("math")
    t.check(abs(math.pi - 3.141592653589793) < 1e-15, "math.pi")
    t.check(abs(math.e - 2.718281828459045) < 1e-15, "math.e")
    t.check_eq(math.floor(3.7), 3, "floor")
    t.check_eq(math.ceil(3.2), 4, "ceil")
    t.check_eq(math.gcd(24, 36), 12, "gcd")

    t.run()


framework.guard(main)
