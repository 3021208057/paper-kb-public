# Sample Space Mapping Sensitivity for Microwave Filters

Jin Park, Lili Wang

## Abstract

This synthetic paper combines space mapping, sensitivity analysis, and simulation-inserted
optimization for microwave filter design. A coarse model guides the fine model while
the sensitivity terms keep the update stable.

## 1 Introduction

Space mapping is useful when a fine EM solver is expensive. Sensitivity analysis helps
reduce the number of design evaluations needed for convergence.

## 2 Method

The workflow alternates between a coarse surrogate and a fine update.
We compute a gradient-like correction at each iteration.

$$
\Delta x = -\alpha \nabla f(x)
$$

## 3 Notes

- space mapping
- sensitivity analysis
- simulation-inserted optimization
- microwave filter

## 4 Conclusion

This synthetic sample broadens the public demo corpus without exposing the real PDFs.
