// synthetic source for the tests of the row tools: it is not DOSBox-X code

static void write_command(Bitu port, Bitu val) {
	Block * blk = &blocks[(port == 0x20) ? 0 : 1];
	if (GCC_UNLIKELY(val & 0x10)) {
		blk->start_init(val);
		return;
	}
	if (val & 0x20) {
		LOG_MSG("rotation is not supported");
		blk->isr &= ~(1 << (val - 0x60));
		blk->check_after_eoi();
	}
}

static void latch(Bitu counter) {
	Block * blk = &blocks[counter];
	blk->last = blk->count = read_count(blk);
	if (counter == 0) {
		blk->irq = blk->output;
	}
}
