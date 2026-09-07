# Sample Neural Macromodeling for GaN HEMT

Mina Chen, Aaron Patel

## Abstract

This sample paper demonstrates nonlinear circuit macromodeling with a recurrent
neural network and device-specific constraints for a GaN HEMT application.
The goal is to preserve transient behavior, trapping effects, and self-heating trends
without running a full device solve every time.

## 1 Introduction

Macromodeling is useful when simulation cost dominates the workflow.
The model is trained from measured or simulated time-domain traces.

## 2 Method

We use a gated recurrent network to approximate the large-signal response.
The update rule blends device state, bias history, and temperature feedback.

$$
h_t = \sigma(W_x x_t + W_h h_{t-1} + b)
$$

## 3 Discussion

- macromodeling
- neural network
- GaN HEMT
- transient response

## 4 Conclusion

This synthetic sample exercises the macromodeling and device tags in the public repo.
