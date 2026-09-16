package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strategylab/engine"
)

func main() {
	strategy := flag.String("strategy", "", "strategy JSON path")
	data := flag.String("data", "", "OHLCV CSV path")
	out := flag.String("out", "", "output JSON path; default stdout")
	flag.Parse()
	if err := run(*strategy, *data, *out); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}
func run(strategy, data, out string) error {
	raw, err := os.ReadFile(strategy)
	if err != nil {
		return err
	}
	s, err := engine.ParseStrategy(raw)
	if err != nil {
		return err
	}
	csv, err := os.ReadFile(data)
	if err != nil {
		return err
	}
	r, err := engine.Run(s, string(csv))
	if err != nil {
		return err
	}
	encoded, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		return err
	}
	encoded = append(encoded, '\n')
	if out != "" {
		return os.WriteFile(out, encoded, 0644)
	}
	_, err = os.Stdout.Write(encoded)
	return err
}
