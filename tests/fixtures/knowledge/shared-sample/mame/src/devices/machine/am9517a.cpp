enum
{
	REGISTER_ADDRESS = 0,
	REGISTER_WORD_COUNT,
	REGISTER_STATUS = 8,
	REGISTER_COMMAND = REGISTER_STATUS,
	REGISTER_REQUEST,
	REGISTER_SINGLE_MASK,
	REGISTER_MODE,
	REGISTER_BYTE_POINTER,
	REGISTER_TEMPORARY,
	REGISTER_MASTER_CLEAR = REGISTER_TEMPORARY,
	REGISTER_CLEAR_MASK,
	REGISTER_MASK
};

uint8_t am9517a_device::read(offs_t offset)
{
	uint8_t data = 0;

	if (!BIT(offset, 3))
	{
		int channel = (offset >> 1) & 0x03;

		switch (offset & 0x01)
		{
		case REGISTER_ADDRESS:
			if (m_msb)
			{
				data = m_channel[channel].m_address >> 8;
			}
			else
			{
				data = m_channel[channel].m_address & 0xff;
			}
			break;

		case REGISTER_WORD_COUNT:
			if (m_msb)
			{
				data = m_channel[channel].m_count >> 8;
			}
			else
			{
				data = m_channel[channel].m_count & 0xff;
			}
			break;
		}

		if (!machine().side_effects_disabled())
			m_msb = !m_msb;
	}
	else
	{
		switch (offset & 0x0f)
		{
		case REGISTER_STATUS:
			data = m_status;
			if (COMMAND_DREQ_ACTIVE_LOW)
				data ^= 0xf0;

			// clear TC bits
			if (!machine().side_effects_disabled())
				m_status &= 0xf0;
			break;

		case REGISTER_TEMPORARY:
			data = m_temp;
			break;

		case REGISTER_MASK:
			data = m_mask;
			break;
		}
	}

	return data;
}
