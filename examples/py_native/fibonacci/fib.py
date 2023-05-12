"""An example binary to test the imports attribute of native Python rules."""


def Fib(n):
  return 1 if n in [0, 1] else Fib(n-1) + Fib(n-2)
