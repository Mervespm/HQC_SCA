

module gen_pulse_custom (

    input wire clk,
    input wire reset_n,
    input wire raw_signal,

    output wire trigger_pulse
);
    logic [1:0] present_pulse;

    assign trigger_pulse = present_pulse[0];
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            present_pulse <= 'h0;
        end
        else begin
            if (raw_signal && present_pulse =='h0)
                present_pulse <= 'h1;
            else if (raw_signal && present_pulse =='h1)
                present_pulse <= 'h2;
            else if (raw_signal && present_pulse =='h2)
                present_pulse <= 'h2;
            else if (!raw_signal && present_pulse =='h2)
                present_pulse <= 'h0;
            else
                present_pulse <= 'h0;
        end
    end

endmodule