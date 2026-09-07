# Sample Waveguide Filter Optimization

Chen Li, Rui Zhang

## Abstract

This sample paper shows the public repository workflow for a waveguide filter project.
It combines model order reduction, space mapping, and surrogate-assisted optimization
to speed up EM design iterations while keeping the fine model in the loop.

## 1 Introduction

Waveguide filter design often needs repeated simulation. A coarse model can guide
the fine model if the mapping is stable enough.

## 2 Method

We use model order reduction (MOR) to accelerate the full-wave solver.
The surrogate is updated with a quasi-Newton outer loop and a space-mapping inner loop.

$$
f(x) = \sum_{i=1}^{n} w_i \phi_i(x)
$$

## 3 Results

| Case | Resonant freq. | Insertion loss |
|---|---:|---:|
| Coarse model | 10.21 GHz | 1.8 dB |
| Fine model | 10.18 GHz | 1.5 dB |

## 4 Conclusion

This sample is synthetic, but it exercises the same parsing, tagging, search, and
comparison paths as a real converted paper.
